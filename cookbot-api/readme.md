# CookBot Cuisine Classifier API

A FastAPI web service that predicts the cuisine type from a list of ingredients. The model is a Logistic Regression classifier trained on TF-IDF features from the Kaggle "What's Cooking?" dataset (39,774 recipes, 20 cuisines). Accuracy: 78.72%.

## Run Locally (without Docker)
```bash
pip install -r requirements.txt
uvicorn app:app --reload --port 8000
```

## Build and Run with Docker
```bash
docker build -t cookbot-api .
docker run -p 8000:8000 cookbot-api
```

Or pull from Docker Hub:
```bash
docker pull sayush2807/cookbot-api:latest
docker run -p 8000:8000 sayush2807/cookbot-api:latest
```

## Endpoints

- `GET /` — Welcome message
- `GET /health` — Model health check
- `POST /predict` — Predict cuisine from ingredients

## Example Request
```bash
curl -X POST http://localhost:8000/predict \
  -H "Content-Type: application/json" \
  -d '{"ingredients": ["soy sauce", "ginger", "garlic", "rice", "sesame oil"]}'
```

## Example Response
```json
{
  "cuisine": "chinese",
  "confidence": 0.7157,
  "top_3": {
    "chinese": 0.7157,
    "korean": 0.2281,
    "japanese": 0.0503
  }
}
```

## MLflow

Model is logged and registered in MLflow Model Registry on a remote GCP Compute Engine server. The API loads the model from MLflow on startup.

## Docker Image

`sayush2807/cookbot-api:latest`