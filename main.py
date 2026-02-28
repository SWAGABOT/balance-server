from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import sqlite3
from datetime import datetime
import json
from contextlib import contextmanager
import threading

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://swagabot.github.io"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ======================================
# ==== БАЗА ДАННЫХ (с блокировками) ====
# ======================================
DATABASE_URL = 'balances.db'

# Создаем локальную блокировку для потоков
db_lock = threading.Lock()

def get_db_connection():
    """Создает новое соединение с БД для каждого потока"""
    conn = sqlite3.connect(DATABASE_URL, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """Инициализация базы данных"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Таблица пользователей с двумя типами баланса
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id TEXT PRIMARY KEY,
            usdt_balance REAL DEFAULT 0,
            swag_balance REAL DEFAULT 0
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
            min_limit REAL DEFAULT 0,
            max_limit REAL DEFAULT 0,
            status TEXT DEFAULT 'active',
            created_at TEXT NOT NULL
        )
    ''')
    
    # Таблица сделок
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id INTEGER NOT NULL,
            buyer_id TEXT NOT NULL,
            seller_id TEXT NOT NULL,
            amount REAL NOT NULL,
            price REAL NOT NULL,
            total REAL NOT NULL,
            fee REAL NOT NULL,
            created_at TEXT NOT NULL
        )
    ''')
    
    conn.commit()
    conn.close()

# Инициализируем БД при старте
init_db()

COMMISSION = 0.02  # 2% комиссия

# ======================================
# ==== БАЛАНСЫ =========================
# ======================================

@app.get("/balance/{user_id}")
def get_balance(user_id: str):
    """Получить баланс пользователя (USDT и SWAG)"""
    with db_lock:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("SELECT usdt_balance, swag_balance FROM users WHERE user_id=?", (user_id,))
        result = cursor.fetchone()
        
        conn.close()
        
        if result:
            return {
                "usdt": float(result["usdt_balance"]),
                "swag": float(result["swag_balance"])
            }
        else:
            # Создаем нового пользователя
            with db_lock:
                conn2 = get_db_connection()
                cursor2 = conn2.cursor()
                cursor2.execute("INSERT INTO users (user_id, usdt_balance, swag_balance) VALUES (?, 0, 0)", (user_id,))
                conn2.commit()
                conn2.close()
            return {"usdt": 0, "swag": 0}

@app.post("/balance/add/{user_id}")
def add_balance(user_id: str, data: dict):
    """Добавить баланс пользователю"""
    currency = data.get('currency', 'swag')
    amount = data.get('amount', 0)
    
    with db_lock:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Проверяем есть ли пользователь
        cursor.execute("SELECT * FROM users WHERE user_id=?", (user_id,))
        user = cursor.fetchone()
        
        if not user:
            cursor.execute("INSERT INTO users (user_id, usdt_balance, swag_balance) VALUES (?, 0, 0)", (user_id,))
        
        # Обновляем баланс
        cursor.execute(f"UPDATE users SET {currency}_balance = {currency}_balance + ? WHERE user_id=?", (amount, user_id))
        conn.commit()
        
        # Получаем новый баланс
        cursor.execute("SELECT usdt_balance, swag_balance FROM users WHERE user_id=?", (user_id,))
        result = cursor.fetchone()
        conn.close()
        
        return {
            "usdt": float(result["usdt_balance"]),
            "swag": float(result["swag_balance"])
        }

# ======================================
# ==== ОРДЕРА ===========================
# ======================================

@app.get("/orders")
def get_orders():
    """Получить все активные ордера"""
    with db_lock:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT id, user_id, type, amount, price, total, min_limit, max_limit, created_at 
            FROM orders 
            WHERE status = 'active'
            ORDER BY price DESC
        ''')
        rows = cursor.fetchall()
        
        orders = []
        for row in rows:
            orders.append({
                "id": row["id"],
                "user_id": row["user_id"],
                "type": row["type"],
                "amount": row["amount"],
                "price": row["price"],
                "total": row["total"],
                "min_limit": row["min_limit"],
                "max_limit": row["max_limit"],
                "created_at": row["created_at"]
            })
        
        conn.close()
        return {"orders": orders}

@app.post("/orders/create")
def create_order(data: dict):
    """Создать новый ордер"""
    user_id = data.get('user_id')
    order_type = data.get('type')
    amount = data.get('amount')
    price = data.get('price')
    min_limit = data.get('min_limit', 0)
    max_limit = data.get('max_limit', 0)
    total = amount * price
    created_at = datetime.now().isoformat()
    
    with db_lock:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT INTO orders (user_id, type, amount, price, total, min_limit, max_limit, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (user_id, order_type, amount, price, total, min_limit, max_limit, 'active', created_at))
        
        conn.commit()
        order_id = cursor.lastrowid
        conn.close()
    
    return {
        "id": order_id,
        "user_id": user_id,
        "type": order_type,
        "amount": amount,
        "price": price,
        "total": total,
        "min_limit": min_limit,
        "max_limit": max_limit,
        "status": "active",
        "created_at": created_at
    }

@app.post("/orders/cancel/{order_id}")
def cancel_order(order_id: int, data: dict):
    """Отменить ордер"""
    user_id = data.get('user_id')
    
    with db_lock:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT user_id FROM orders 
            WHERE id = ? AND status = 'active'
        ''', (order_id,))
        result = cursor.fetchone()
        
        if not result:
            conn.close()
            return {"error": "Order not found"}, 404
        
        if result["user_id"] != user_id:
            conn.close()
            return {"error": "Not your order"}, 403
        
        cursor.execute('''
            UPDATE orders SET status = 'cancelled' 
            WHERE id = ?
        ''', (order_id,))
        conn.commit()
        conn.close()
    
    return {"success": True}

@app.post("/orders/execute/{order_id}")
def execute_order(order_id: int, data: dict):
    """Исполнить ордер (купить/продать)"""
    buyer_id = data.get('user_id')
    amount = data.get('amount')
    
    with db_lock:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT * FROM orders 
            WHERE id = ? AND status = 'active'
        ''', (order_id,))
        order = cursor.fetchone()
        
        if not order:
            conn.close()
            return {"error": "Order not found"}, 404
        
        order_data = {
            "id": order["id"],
            "user_id": order["user_id"],
            "type": order["type"],
            "amount": order["amount"],
            "price": order["price"],
            "total": order["total"],
            "min_limit": order["min_limit"],
            "max_limit": order["max_limit"]
        }
        
        # Проверка лимитов
        if order_data['min_limit'] > 0 and amount < order_data['min_limit']:
            conn.close()
            return {"error": f"Minimum amount is {order_data['min_limit']} SWAG"}, 400
        
        if order_data['max_limit'] > 0 and amount > order_data['max_limit']:
            conn.close()
            return {"error": f"Maximum amount is {order_data['max_limit']} SWAG"}, 400
        
        if amount > order_data['amount']:
            conn.close()
            return {"error": f"Not enough SWAG. Available: {order_data['amount']}"}, 400
        
        total_price = amount * order_data['price']
        fee = total_price * COMMISSION
        
        # Получаем балансы участников
        cursor.execute("SELECT * FROM users WHERE user_id=?", (buyer_id,))
        buyer = cursor.fetchone()
        cursor.execute("SELECT * FROM users WHERE user_id=?", (order_data['user_id'],))
        seller = cursor.fetchone()
        
        if not buyer:
            cursor.execute("INSERT INTO users (user_id, usdt_balance, swag_balance) VALUES (?, 0, 0)", (buyer_id,))
            buyer = {"usdt_balance": 0, "swag_balance": 0}
        
        if not seller:
            cursor.execute("INSERT INTO users (user_id, usdt_balance, swag_balance) VALUES (?, 0, 0)", (order_data['user_id'],))
            seller = {"usdt_balance": 0, "swag_balance": 0}
        
        if order_data['type'] == 'sell':
            # Покупка у продавца
            if buyer["usdt_balance"] < total_price:
                conn.close()
                return {"error": "Insufficient USDT balance"}, 400
            
            # Обновляем балансы
            cursor.execute("UPDATE users SET usdt_balance = usdt_balance - ? WHERE user_id=?", (total_price, buyer_id))
            cursor.execute("UPDATE users SET swag_balance = swag_balance + ? WHERE user_id=?", (amount, buyer_id))
            cursor.execute("UPDATE users SET usdt_balance = usdt_balance + ? WHERE user_id=?", (total_price - fee, order_data['user_id']))
            
        else:  # buy
            # Продажа покупателю
            if buyer["swag_balance"] < amount:
                conn.close()
                return {"error": "Insufficient SWAG balance"}, 400
            
            # Обновляем балансы
            cursor.execute("UPDATE users SET swag_balance = swag_balance - ? WHERE user_id=?", (amount, buyer_id))
            cursor.execute("UPDATE users SET usdt_balance = usdt_balance + ? WHERE user_id=?", (total_price, buyer_id))
            cursor.execute("UPDATE users SET swag_balance = swag_balance + ? WHERE user_id=?", (amount - fee, order_data['user_id']))
        
        # Обновляем ордер
        new_amount = order_data['amount'] - amount
        if new_amount == 0:
            cursor.execute("UPDATE orders SET status = 'completed' WHERE id=?", (order_id,))
        else:
            cursor.execute("UPDATE orders SET amount = ? WHERE id=?", (new_amount, order_id))
        
        # Сохраняем сделку
        cursor.execute('''
            INSERT INTO trades (order_id, buyer_id, seller_id, amount, price, total, fee, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (order_id, buyer_id, order_data['user_id'], amount, order_data['price'], total_price, fee, datetime.now().isoformat()))
        
        conn.commit()
        conn.close()
    
    return {
        "success": True,
        "amount": amount,
        "total": total_price,
        "fee": fee,
        "new_order_amount": new_amount
    }

@app.get("/orders/user/{user_id}")
def get_user_orders(user_id: str):
    """Получить ордера пользователя"""
    with db_lock:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT id, type, amount, price, total, min_limit, max_limit, status, created_at 
            FROM orders 
            WHERE user_id = ?
            ORDER BY created_at DESC
        ''', (user_id,))
        rows = cursor.fetchall()
        
        orders = []
        for row in rows:
            orders.append({
                "id": row["id"],
                "type": row["type"],
                "amount": row["amount"],
                "price": row["price"],
                "total": row["total"],
                "min_limit": row["min_limit"],
                "max_limit": row["max_limit"],
                "status": row["status"],
                "created_at": row["created_at"]
            })
        
        conn.close()
        return {"orders": orders}

@app.get("/")
def root():
    return {
        "status": "online",
        "commission": f"{COMMISSION*100}%",
        "endpoints": {
            "balance": "/balance/{user_id}",
            "add_balance": "/balance/add/{user_id}",
            "orders": "/orders",
            "create_order": "/orders/create",
            "cancel_order": "/orders/cancel/{order_id}",
            "execute_order": "/orders/execute/{order_id}",
            "user_orders": "/orders/user/{user_id}"
        }
    }
