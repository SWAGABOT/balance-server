from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import sqlite3

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://swagabot.github.io"],
    allow_methods=["*"],
)

conn = sqlite3.connect('balances.db', check_same_thread=False)
cursor = conn.cursor()
cursor.execute('CREATE TABLE IF NOT EXISTS users (user_id TEXT PRIMARY KEY, balance INTEGER DEFAULT 0)')
conn.commit()

@app.get("/balance/{user_id}")
def get_balance(user_id: str):
    cursor.execute("SELECT balance FROM users WHERE user_id=?", (user_id,))
    result = cursor.fetchone()
    return {"balance": result[0] if result else 0}

@app.post("/balance/{user_id}/add/{amount}")
def add_balance(user_id: str, amount: int):
    cursor.execute("INSERT OR IGNORE INTO users (user_id, balance) VALUES (?, 0)", (user_id,))
    cursor.execute("UPDATE users SET balance = balance + ? WHERE user_id=?", (amount, user_id))
    conn.commit()
    cursor.execute("SELECT balance FROM users WHERE user_id=?", (user_id,))
    new_balance = cursor.fetchone()[0]
    return {"balance": new_balance}