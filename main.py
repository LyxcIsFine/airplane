from fastapi import FastAPI, HTTPException, Depends, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
import pandas as pd
import sqlite3
import hashlib
import os

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)



@app.get("/", response_class=HTMLResponse)
def index():
    with open("index.html", "r", encoding="utf-8") as f:
        return f.read()

routes_df = pd.read_csv("routes.csv")
forecast_df = pd.read_csv("forecast.csv")

def init_db():
    if not os.path.exists("users.db"):
        conn = sqlite3.connect("users.db")
        cursor = conn.cursor()
        cursor.execute("CREATE TABLE users (username TEXT PRIMARY KEY, password TEXT, token TEXT)")
        conn.commit()
        conn.close()

init_db()

def get_db():
    return sqlite3.connect("users.db")

class UserRegister(BaseModel):
    username: str
    password: str

class UserLogin(BaseModel):
    username: str
    password: str

class PredictionRequest(BaseModel):
    route: str
    date: str
    price: float

def verify_token(authorization: str = Header(None)):
    if not authorization:
        raise HTTPException(status_code=401, detail="Токен не передан, войдите заново")
    parts = authorization.split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(status_code=401, detail="Неверный формат токена")
    token = parts[1].strip()
    if not token or token in ("null", "undefined"):
        raise HTTPException(status_code=401, detail="Токена нет, войдите заново")
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT username FROM users WHERE token=?", (token,))
    user = cursor.fetchone()
    conn.close()
    if not user:
        raise HTTPException(status_code=401, detail="Неверный токен")
    return user[0]

@app.post("/register")
def register(user: UserRegister):
    conn = get_db()
    cursor = conn.cursor()
    hashed = hashlib.sha256(user.password.encode()).hexdigest()
    token = hashlib.sha256(user.username.encode()).hexdigest()
    try:
        cursor.execute("INSERT INTO users (username, password, token) VALUES (?, ?, ?)", (user.username, hashed, token))
        conn.commit()
        return {"message": "Пользователь зарегистрирован"}
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=400, detail="Пользователь уже существует")
    finally:
        conn.close()

@app.post("/login")
def login(user: UserLogin):
    conn = get_db()
    cursor = conn.cursor()
    hashed = hashlib.sha256(user.password.encode()).hexdigest()
    cursor.execute("SELECT username, token FROM users WHERE username=? AND password=?", (user.username, hashed))
    result = cursor.fetchone()
    conn.close()
    if not result:
        raise HTTPException(status_code=401, detail="Неверное имя пользователя или пароль")
    return {"username": result[0], "token": result[1]}

@app.post("/predict")
def predict(request: PredictionRequest, username: str = Depends(verify_token)):
    try:
        row = forecast_df[(forecast_df["route"] == request.route) & (forecast_df["date"] == request.date)]
        if row.empty:
            raise HTTPException(status_code=404, detail="Рейс не найден")

        info = routes_df[routes_df["route"] == request.route].iloc[0]
        base_price = info["base_price"]
        sensitivity = info["price_sensitivity"]
        cost = info["cost_per_passenger"]
        seats = int(row["seats"].values[0])

        quantiles = ["0.1", "0.2", "0.3", "0.4", "0.5", "0.6", "0.7", "0.8", "0.9"]
        demands = []

        for q in quantiles:
            base_demand = row[f"{q}_base_demand"].values[0]
            demand = max(0, base_demand - sensitivity * (request.price - base_price))
            demands.append(round(min(seats, demand)))

        median_sold = demands[4]
        profit = round((request.price - cost) * median_sold)

        return {
            "calculated_demand": demands[4],
            "seats": seats,
            "sold_tickets": median_sold,
            "profit": profit,
            "quantiles": {
                "labels": ["10%", "20%", "30%", "40%", "50%", "60%", "70%", "80%", "90%"],
                "data": demands
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Внутренняя ошибка: {e}. Колонки прогноза: {list(forecast_df.columns)}")