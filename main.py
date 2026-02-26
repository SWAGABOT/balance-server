from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import sqlite3
from datetime import datetime
import json

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://swagabot.github.io"],
    allow_methods=["*"],
    allow_headers=["*"],
)

conn = sqlite3.connect('balances.db', check_same_thread=False)
cursor = conn.cursor()

# Таблица пользователей
cursor.execute('''
    CREATE TABLE IF NOT EXISTS users (
        user_id TEXT PRIMARY KEY,
        balance INTEGER DEFAULT 0
    )
''')

# Таблица ордеров
cursor.execute('''
    CREATE TABLE IF NOT EXISTS orders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT NOT NULL,
        type TEXT NOT NULL,
        amount REAL NOT NULL,
        price REAL NOT NULL,
        total REAL NOT NULL,
        status TEXT DEFAULT 'active',
        created_at TEXT NOT NULL
    )
''')
conn.commit()

# ======================================
# ==== БАЛАНСЫ =========================
# ======================================

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

# ======================================
# ==== ОРДЕРА ===========================
# ======================================

@app.get("/orders")
def get_orders():
    """Получить все активные ордера"""
    cursor.execute('''
        SELECT id, user_id, type, amount, price, total, created_at 
        FROM orders 
        WHERE status = 'active'
        ORDER BY created_at DESC
    ''')
    rows = cursor.fetchall()
    
    orders = []
    for row in rows:
        orders.append({
            "id": row[0],
            "user_id": row[1],
            "type": row[2],
            "amount": row[3],
            "price": row[4],
            "total": row[5],
            "created_at": row[6]
        })
    return {"orders": orders}

@app.post("/orders/create")
def create_order(data: dict):
    """Создать новый ордер"""
    user_id = data.get('user_id')
    order_type = data.get('type')
    amount = data.get('amount')
    price = data.get('price')
    total = amount * price
    created_at = datetime.now().isoformat()
    
    cursor.execute('''
        INSERT INTO orders (user_id, type, amount, price, total, status, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    ''', (user_id, order_type, amount, price, total, 'active', created_at))
    
    conn.commit()
    order_id = cursor.lastrowid
    
    return {
        "id": order_id,
        "user_id": user_id,
        "type": order_type,
        "amount": amount,
        "price": price,
        "total": total,
        "created_at": created_at,
        "status": "active"
    }

@app.post("/orders/cancel/{order_id}")
def cancel_order(order_id: int, data: dict):
    """Отменить ордер (только владелец)"""
    user_id = data.get('user_id')
    
    # Проверяем, что ордер принадлежит этому пользователю
    cursor.execute('''
        SELECT user_id FROM orders 
        WHERE id = ? AND status = 'active'
    ''', (order_id,))
    result = cursor.fetchone()
    
    if not result:
        return {"error": "Order not found"}, 404
    
    if result[0] != user_id:
        return {"error": "Not your order"}, 403
    
    cursor.execute('''
        UPDATE orders SET status = 'cancelled' 
        WHERE id = ?
    ''', (order_id,))
    conn.commit()
    
    return {"success": True}

@app.get("/orders/user/{user_id}")
def get_user_orders(user_id: str):
    """Получить ордера конкретного пользователя"""
    cursor.execute('''
        SELECT id, type, amount, price, total, status, created_at 
        FROM orders 
        WHERE user_id = ?
        ORDER BY created_at DESC
    ''', (user_id,))
    rows = cursor.fetchall()
    
    orders = []
    for row in rows:
        orders.append({
            "id": row[0],
            "type": row[1],
            "amount": row[2],
            "price": row[3],
            "total": row[4],
            "status": row[5],
            "created_at": row[6]
        })
    return {"orders": orders}

@app.get("/")
def root():
    return {
        "status": "online",
        "endpoints": {
            "balance": "/balance/{user_id}",
            "add_balance": "/balance/{user_id}/add/{amount}",
            "orders": "/orders",
            "create_order": "/orders/create",
            "cancel_order": "/orders/cancel/{order_id}",
            "user_orders": "/orders/user/{user_id}"
        }
    }
