from django.shortcuts import render
from workout.models import Workout, Recommendation
from workout.serializers import WorkoutSerializer, RecommendationSerializer
from .models import Workout
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework import status
import requests
from rest_framework.permissions import IsAuthenticated
from django.core.exceptions import ObjectDoesNotExist
from users.views import IsAccessToken

#For llm prompting
from backend.settings import API_KEY, MODEL_VERSION
from .llm_config import *
import google.generativeai as genai
from users.models import HealthData
from datetime import *
from django.utils import timezone


class CreateWorkoutView(APIView):
    permission_classes = [IsAuthenticated, IsAccessToken] # Ensures only authenticated users using access token can access this API

    '''Create Workout'''
    def post(self, request):
        serializer = WorkoutSerializer(data=request.data)
        if serializer.is_valid():
            try:
                llm = LlmConnection()
                workout = llm.requestWorkout(serializer)

            except Exception as e:
                print(f"[ERROR]:{str(e)}" )
                if hasattr(e, 'code'):
                    print(f"[ERROR CODE]: {e.code}")
                return Response({"error:" "Workout Generation Failed"}, status = status.HTTP_500_INTERNAL_SERVER_ERROR)
            
            serializer.save(user=request.user, llm_suggested_workout = [workout])
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    

class WorkoutListView(APIView):
    permission_classes = [IsAuthenticated, IsAccessToken] # Ensures only authenticated users using access token can access this API

    '''View workout history by user'''
    def get(self, request):
        workouts = Workout.objects.filter(user=request.user)
        serializer = WorkoutSerializer(workouts, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)
    
class WorkoutView(APIView):
    permission_classes = [IsAuthenticated, IsAccessToken] # Ensures only authenticated users using access token can access this API

    '''View workout'''
    def get(self, request, id):
        try:
            workout = Workout.objects.get(user=request.user, id=id)
            serializer = WorkoutSerializer(workout)
            return Response(serializer.data, status=status.HTTP_200_OK)
        
        except Workout.DoesNotExist:
            return Response({"error": "Workout not found."}, status=status.HTTP_404_NOT_FOUND)
        
    '''Modify Workout'''
    def put(self, request, id):
        try:
            workout = Workout.objects.get(user=request.user, id=id)
            serializer = WorkoutSerializer(workout, data=request.data)
            if serializer.is_valid():
                serializer.save()
                return Response(serializer.data, status=status.HTTP_200_OK)
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        except Workout.DoesNotExist:
            return Response({"error": "Workout not found."}, status=status.HTTP_404_NOT_FOUND)
        
    '''Patch Workout'''
    def patch(self, request, id):
        try:
            workout = Workout.objects.get(user=request.user, id=id)
            serializer = WorkoutSerializer(workout, data=request.data, partial=True)
            if serializer.is_valid():
                # Only contacts the llm if sending suggested changes
                if "llm_suggested_changes" in request.data:
                    #Extract the change request and workout history and append it to the list of requests
                    print("[INFO]: Changing workout. Generating history")
                    change_history = getattr(workout, "llm_suggested_changes")
                    workout_history = getattr(workout, "llm_suggested_workout")

                    if change_history == []:
                        change_history = serializer.validated_data.get("llm_suggested_changes")
                    else:
                        change_history.extend(serializer.validated_data.get("llm_suggested_changes"))

                    try:
                        llm = LlmConnection()
                        new_workout = llm.changeWorkout(change_history, workout_history)

                    except Exception as e:
                        print(f"[ERROR]:{str(e)}" )
                        if hasattr(e, 'code'):
                            print(f"[ERROR CODE]: {e.code}")
                        return Response({"error:" "Workout Generation Failed"}, status = status.HTTP_500_INTERNAL_SERVER_ERROR)

                    workout_history.append(new_workout)
                    serializer.save(llm_suggested_changes = change_history, llm_suggested_workout = workout_history)
                serializer.save()
                return Response(serializer.data, status=status.HTTP_200_OK)
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        except Workout.DoesNotExist:
            return Response({"error": "Workout not found."}, status=status.HTTP_404_NOT_FOUND)
        
    '''Delete Workout'''
    def delete(self, request, id):
        try:
            workout = Workout.objects.get(user=request.user, id=id)
            workout.delete()
            return Response({"message": "Workout deleted successfully."}, status=status.HTTP_200_OK)
        except Workout.DoesNotExist:
            return Response({"error": "Workout not found."}, status=status.HTTP_404_NOT_FOUND)

class WorkoutRecommendation(APIView):
    permission_classes = [IsAuthenticated, IsAccessToken]
    workout_history_max = 3
    no_history_msg = '{"recommendation": "Try creating a workout to get started!", "parameters": {"length":"", "workout_type":"", "target_area":""}}'

    def reduceWorkoutHistory(self, workout_count):
        return workout_count if workout_count < self.workout_history_max else self.workout_history_max

    def get(self, request):

        #Search for recos from today
        try:
            recommendation = Recommendation.objects.get(user=request.user, created__date = timezone.now())
            serializer = RecommendationSerializer(recommendation)
            return Response(serializer.data, status=status.HTTP_200_OK)

        #If not reco for today, create one
        except Recommendation.DoesNotExist:
            workout_count = Workout.objects.filter(user = request.user).count()
            num_workouts = self.reduceWorkoutHistory(workout_count)

            if num_workouts == 0:
                return Response(RecommendationSerializer(Recommendation(recommendation = self.no_history_msg)).data, status=status.HTTP_200_OK)

            #Request a new recommendation for the last N workouts
            else:
                last_n_workouts = Workout.objects.filter(user=request.user).order_by('-id')[:num_workouts]
                final_suggested_workout = []
                for workout_n in last_n_workouts:
                    suggested_list = getattr(workout_n, 'llm_suggested_workout')
                    final_suggested_workout.append(suggested_list[-1])
                
                try:
                    llm = LlmConnection()
                    response = llm.generateRecommendation(final_suggested_workout)
              
                except Exception as e:
                    print(f"[ERROR]:{str(e)}" )
                    if hasattr(e, 'code'):
                        print(f"[ERROR CODE]: {e.code}")
                    return Response({"error:" "Recommendation Generation Failed"}, status = status.HTTP_500_INTERNAL_SERVER_ERROR)

                recommendation = Recommendation.objects.create(user = request.user, recommendation = response)
                return Response(RecommendationSerializer(recommendation).data, status = status.HTTP_200_OK)



    '''Patch Workout'''
    def patch(self, request, id):
        try:
            workout = Workout.objects.get(user=request.user, id=id)
            serializer = WorkoutSerializer(workout, data=request.data, partial=True)
            if serializer.is_valid():
                # Only contacts the llm if sending suggested changes
                if "llm_suggested_changes" in request.data:
                    #Extract the change request and workout history and append it to the list of requests
                    print("[INFO]: Changing workout. Generating history")
                    change_history = getattr(workout, "llm_suggested_changes")
                    workout_history = getattr(workout, "llm_suggested_workout")

                    if change_history == []:
                        change_history = serializer.validated_data.get("llm_suggested_changes")
                    else:
                        change_history.extend(serializer.validated_data.get("llm_suggested_changes"))

                    try:
                        llm = LlmConnection()
                        new_workout = llm.changeWorkout(change_history, workout_history)

                    except Exception as e:
                        print(f"[ERROR]:{str(e)}" )
                        if hasattr(e, 'code'):
                            print(f"[ERROR CODE]: {e.code}")
                        return Response({"error:" "Workout Generation Failed"}, status = status.HTTP_500_INTERNAL_SERVER_ERROR)

                    workout_history.append(new_workout)
                    serializer.save(llm_suggested_changes = change_history, llm_suggested_workout = workout_history)
                serializer.save()
                return Response(serializer.data, status=status.HTTP_200_OK)
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        except Workout.DoesNotExist:
            return Response({"error": "Workout not found."}, status=status.HTTP_404_NOT_FOUND)

    '''Delete Workout'''
    def delete(self, request, id):
        try:
            workout = Workout.objects.get(user=request.user, id=id)
            workout.delete()
            return Response({"message": "Workout deleted successfully."}, status=status.HTTP_200_OK)
        except Workout.DoesNotExist:
            return Response({"error": "Workout not found."}, status=status.HTTP_404_NOT_FOUND)


''' Used to connect and query llm'''
class LlmConnection():

    api_key = API_KEY
    model_version = MODEL_VERSION
    model = genai.GenerativeModel(model_version)
    health_obj = HealthData.objects.first()

    def __init__(self):
        genai.configure(api_key = self.api_key)
        return

    '''Request a workout from the llm'''
    def requestWorkout(self, serializer):
        print("[INFO]: Connecting to Gemini")
        prompt = self.generatePrompt(serializer.validated_data)
        response = self.model.generate_content(prompt)
        return response.candidates[0].content.parts[0].text

    '''Make changes to the current llm workout'''
    def changeWorkout(self, change_history, workout_history):
        #Add sending the workout prompt info as history
        print("[INFO]: Sending workout history to Gemini")
        chat = self.model.start_chat(
                    history = [
                        {"role": "user", "parts": change_history},
                        {"role": "model", "parts": workout_history}
                    ]
        ) 
        response = chat.send_message(prompt_end)
        return response.candidates[0].content.parts[0].text

    '''Generates llm prompts'''
    def generatePrompt(self, workout_data):
        print("[INFO]: Creating Prompt")
        #For serializers
        prompt = prompt_start
        for key in workout_keys:
            val = workout_data.get(key)
            prompt += str(key) + ": " + str(val) + "\n"
        #For objects
        for key in health_keys:
            val = getattr(self.health_obj, key)
            prompt += str(key) + ": " + str(val) + "\n"

        prompt += prompt_end
        return prompt
    
    def generateRecommendation(self, workout_list):
        print("[INFO]: Creating Recommendation")
        prompt = reco_start + str(workout_list) + '\n' + reco_end
        response = self.model.generate_content(prompt)
        return response.candidates[0].content.parts[0].text









