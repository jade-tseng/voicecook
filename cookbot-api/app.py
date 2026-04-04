from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List
import joblib
import os
import mlflow
from mlflow.tracking import MlflowClient

app = FastAPI(title="CookBot Cuisine Classifier API")

MLFLOW_TRACKING_URI = "http://34.60.170.139:5000"
MODEL_NAME = "cuisine-classifier"
MODEL_VERSION = "1"

model = None

@app.on_event("startup")
def load_model():
    global model
    try:
        client = MlflowClient(MLFLOW_TRACKING_URI)
        version = client.get_model_version(MODEL_NAME, MODEL_VERSION)
        run_id = version.run_id
        
        # Download artifact from MLflow
        mlflow.set_tracking_uri(MLFLOW_TRACKING_URI)
        artifact_path = mlflow.artifacts.download_artifacts(
            run_id=run_id,
            artifact_path="cuisine_pipeline.joblib"
        )
        model = joblib.load(artifact_path)
        print("Model loaded successfully from MLflow Registry")
    except Exception as e:
        print(f"Error loading model: {e}")
        raise e


class PredictRequest(BaseModel):
    ingredients: List[str]

    class Config:
        json_schema_extra = {
            "example": {
                "ingredients": ["soy sauce", "ginger", "garlic", "rice", "sesame oil"]
            }
        }


class PredictResponse(BaseModel):
    cuisine: str
    confidence: float
    top_3: dict


@app.get("/")
def root():
    return {"message": "Welcome to CookBot Cuisine Classifier API"}


@app.get("/health")
def health():
    if model is None:
        raise HTTPException(status_code=503, detail="Model not loaded")
    return {"status": "healthy", "model": MODEL_NAME, "version": MODEL_VERSION}


@app.post("/predict", response_model=PredictResponse)
def predict(request: PredictRequest):
    if model is None:
        raise HTTPException(status_code=503, detail="Model not loaded")
    
    if not request.ingredients:
        raise HTTPException(status_code=400, detail="Ingredients list cannot be empty")
    
    ingredients_text = ' '.join([i.lower().strip() for i in request.ingredients])
    
    prediction = model.predict([ingredients_text])[0]
    probabilities = model.predict_proba([ingredients_text])[0]
    classes = model.classes_
    
    confidence = float(probabilities.max())
    
    top_3_idx = probabilities.argsort()[-3:][::-1]
    top_3 = {classes[i]: round(float(probabilities[i]), 4) for i in top_3_idx}
    
    return PredictResponse(
        cuisine=prediction,
        confidence=round(confidence, 4),
        top_3=top_3
    )