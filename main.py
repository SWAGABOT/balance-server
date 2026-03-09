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

# Таблица пользователей (с замороженными средствами)
cursor.execute('''
    CREATE TABLE IF NOT EXISTS users (
        user_id TEXT PRIMARY KEY,
        usdt_balance REAL DEFAULT 0,
        swag_balance REAL DEFAULT 0,
        usdt_frozen REAL DEFAULT 0,
        swag_frozen REAL DEFAULT 0
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
        fee REAL DEFAULT 0,
        created_at TEXT NOT NULL
    )
''')
conn.commit()

# Комиссия отключена (0%)
COMMISSION = 0.00

# ======================================
# ==== БАЛАНСЫ =========================
# ======================================

@app.get("/balance/{user_id}")
def get_balance(user_id: str):
    cursor.execute("SELECT usdt_balance, swag_balance, usdt_frozen, swag_frozen FROM users WHERE user_id=?", (user_id,))
    result = cursor.fetchone()
    if result:
        return {
            "usdt": result[0],
            "swag": result[1],
            "usdt_frozen": result[2],
            "swag_frozen": result[3]
        }
    else:
        cursor.execute("INSERT INTO users (user_id, usdt_balance, swag_balance) VALUES (?, 0, 0)", (user_id,))
        conn.commit()
        return {"usdt": 0, "swag": 0, "usdt_frozen": 0, "swag_frozen": 0}

@app.post("/balance/add/{user_id}")
def add_balance(user_id: str, data: dict):
    currency = data.get('currency', 'usdt')
    amount = data.get('amount', 0)
    
    cursor.execute(f"INSERT OR IGNORE INTO users (user_id, usdt_balance, swag_balance) VALUES (?, 0, 0)", (user_id,))
    cursor.execute(f"UPDATE users SET {currency}_balance = {currency}_balance + ? WHERE user_id=?", (amount, user_id))
    conn.commit()
    
    cursor.execute("SELECT usdt_balance, swag_balance FROM users WHERE user_id=?", (user_id,))
    result = cursor.fetchone()
    return {"usdt": result[0], "swag": result[1]}

# ======================================
# ==== СТАТИСТИКА ПОЛЬЗОВАТЕЛЯ =========
# ======================================

@app.get("/user/stats/{user_id}")
def get_user_stats(user_id: str):
    """Возвращает количество сделок и общий объём для пользователя"""
    cursor.execute('''
        SELECT COUNT(*) as trades_count, SUM(total) as total_volume 
        FROM trades 
        WHERE buyer_id = ? OR seller_id = ?
    ''', (user_id, user_id))
    
    result = cursor.fetchone()
    trades_count = result[0] or 0
    total_volume = result[1] or 0
    
    return {
        "trades": trades_count,
        "volume": total_volume
    }

# ======================================
# ==== ОРДЕРА ===========================
# ======================================

@app.get("/orders")
def get_orders():
    """Получить все активные ордера"""
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
            "id": row[0],
            "user_id": row[1],
            "type": row[2],
            "amount": row[3],
            "price": row[4],
            "total": row[5],
            "min_limit": row[6],
            "max_limit": row[7],
            "created_at": row[8]
        })
    return {"orders": orders}

@app.post("/orders/create")
def create_order(data: dict):
    """Создать новый ордер с проверкой баланса и заморозкой"""
    user_id = data.get('user_id')
    order_type = data.get('type')
    amount = data.get('amount')
    price = data.get('price')
    min_limit = data.get('min_limit', 0)
    max_limit = data.get('max_limit', 0)
    total = amount * price
    created_at = datetime.now().isoformat()
    
    # Получаем баланс пользователя
    cursor.execute("SELECT usdt_balance, swag_balance FROM users WHERE user_id=?", (user_id,))
    user = cursor.fetchone()
    if not user:
        cursor.execute("INSERT INTO users (user_id, usdt_balance, swag_balance) VALUES (?, 0, 0)", (user_id,))
        conn.commit()
        usdt, swag = 0, 0
    else:
        usdt, swag = user
    
    # Проверяем достаточно ли средств
    if order_type == 'sell' and swag < amount:
        return {"error": f"Insufficient SWAG balance. You have {swag} SWAG"}, 400
    if order_type == 'buy' and usdt < total:
        return {"error": f"Insufficient USDT balance. You have {usdt} USDT"}, 400
    
    # Замораживаем средства
    if order_type == 'sell':
        cursor.execute("UPDATE users SET swag_balance = swag_balance - ?, swag_frozen = swag_frozen + ? WHERE user_id=?", 
                      (amount, amount, user_id))
    else:
        cursor.execute("UPDATE users SET usdt_balance = usdt_balance - ?, usdt_frozen = usdt_frozen + ? WHERE user_id=?", 
                      (total, total, user_id))
    
    # Создаем ордер
    cursor.execute('''
        INSERT INTO orders (user_id, type, amount, price, total, min_limit, max_limit, status, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (user_id, order_type, amount, price, total, min_limit, max_limit, 'active', created_at))
    
    conn.commit()
    order_id = cursor.lastrowid
    
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
    """Отменить ордер и разморозить средства"""
    user_id = data.get('user_id')
    
    cursor.execute('''
        SELECT user_id, type, amount, price, total FROM orders 
        WHERE id = ? AND status = 'active'
    ''', (order_id,))
    result = cursor.fetchone()
    
    if not result:
        return {"error": "Order not found"}, 404
    
    seller_id, order_type, amount, price, total = result
    
    if seller_id != user_id:
        return {"error": "Not your order"}, 403
    
    # Размораживаем средства
    if order_type == 'sell':
        cursor.execute("UPDATE users SET swag_balance = swag_balance + ?, swag_frozen = swag_frozen - ? WHERE user_id=?", 
                      (amount, amount, user_id))
    else:
        cursor.execute("UPDATE users SET usdt_balance = usdt_balance + ?, usdt_frozen = usdt_frozen - ? WHERE user_id=?", 
                      (total, total, user_id))
    
    cursor.execute('''
        UPDATE orders SET status = 'cancelled' 
        WHERE id = ?
    ''', (order_id,))
    conn.commit()
    
    return {"success": True}

@app.post("/orders/execute/{order_id}")
def execute_order(order_id: int, data: dict):
    """Исполнить ордер (купить/продать)"""
    buyer_id = data.get('user_id')
    amount = data.get('amount')
    
    cursor.execute('''
        SELECT * FROM orders 
        WHERE id = ? AND status = 'active'
    ''', (order_id,))
    order = cursor.fetchone()
    
    if not order:
        return {"error": "Order not found"}, 404
    
    order_data = {
        "id": order[0],
        "seller_id": order[1],
        "type": order[2],
        "amount": order[3],
        "price": order[4],
        "total": order[5],
        "min_limit": order[6],
        "max_limit": order[7]
    }
    
    # Запрещаем торговлю с самим собой
    if buyer_id == order_data['seller_id']:
        return {"error": "Cannot trade with yourself"}, 400
    
    # Проверка лимитов
    if order_data['min_limit'] > 0 and amount < order_data['min_limit']:
        return {"error": f"Minimum amount is {order_data['min_limit']} SWAG"}, 400
    
    if order_data['max_limit'] > 0 and amount > order_data['max_limit']:
        return {"error": f"Maximum amount is {order_data['max_limit']} SWAG"}, 400
    
    if amount > order_data['amount']:
        return {"error": f"Not enough SWAG. Available: {order_data['amount']}"}, 400
    
    total_price = amount * order_data['price']
    fee = total_price * COMMISSION
    
    # Получаем балансы участников
    cursor.execute("SELECT usdt_balance, swag_balance, usdt_frozen, swag_frozen FROM users WHERE user_id=?", (buyer_id,))
    buyer = cursor.fetchone()
    cursor.execute("SELECT usdt_balance, swag_balance, usdt_frozen, swag_frozen FROM users WHERE user_id=?", (order_data['seller_id'],))
    seller = cursor.fetchone()
    
    if not buyer or not seller:
        return {"error": "User not found"}, 404
    
    # Исполнение сделки в зависимости от типа ордера
    if order_data['type'] == 'sell':
        # Покупатель покупает у продавца (покупатель отдает USDT, получает SWAG)
        # Проверяем достаточно ли USDT у покупателя
        if buyer[0] < total_price:
            return {"error": "Insufficient USDT balance"}, 400
        
        # Обновляем балансы
        # У покупателя списываем USDT
        cursor.execute("UPDATE users SET usdt_balance = usdt_balance - ? WHERE user_id=?", (total_price, buyer_id))
        # Покупателю начисляем SWAG
        cursor.execute("UPDATE users SET swag_balance = swag_balance + ? WHERE user_id=?", (amount, buyer_id))
        
        # У продавца списываем SWAG (из замороженных)
        cursor.execute("UPDATE users SET swag_frozen = swag_frozen - ? WHERE user_id=?", (amount, order_data['seller_id']))
        # Продавцу начисляем USDT (минус комиссия)
        cursor.execute("UPDATE users SET usdt_balance = usdt_balance + ? WHERE user_id=?", 
                      (total_price - fee, order_data['seller_id']))
        
    else:  # buy ордер (кто-то продает покупателю)
        # Продавец продает покупателю (продавец отдает SWAG, получает USDT)
        # Проверяем достаточно ли SWAG у продавца (buyer_id)
        if buyer[1] < amount:
            return {"error": "Insufficient SWAG balance"}, 400
        
        # Обновляем балансы
        # У продавца (buyer_id) списываем SWAG
        cursor.execute("UPDATE users SET swag_balance = swag_balance - ? WHERE user_id=?", (amount, buyer_id))
        # Продавцу начисляем USDT
        cursor.execute("UPDATE users SET usdt_balance = usdt_balance + ? WHERE user_id=?", (total_price, buyer_id))
        
        # У покупателя (владельца ордера) списываем USDT из замороженных
        cursor.execute("UPDATE users SET usdt_frozen = usdt_frozen - ? WHERE user_id=?", 
                      (total_price, order_data['seller_id']))
        # Покупателю начисляем SWAG (минус комиссия)
        cursor.execute("UPDATE users SET swag_balance = swag_balance + ? WHERE user_id=?", 
                      (amount - fee, order_data['seller_id']))
    
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
    ''', (order_id, buyer_id, order_data['seller_id'], amount, order_data['price'], total_price, fee, datetime.now().isoformat()))
    
    conn.commit()
    
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
    cursor.execute('''
        SELECT * FROM orders 
        WHERE user_id = ?
        ORDER BY created_at DESC
    ''', (user_id,))
    rows = cursor.fetchall()
    
    orders = []
    for row in rows:
        orders.append({
            "id": row[0],
            "type": row[2],
            "amount": row[3],
            "price": row[4],
            "total": row[5],
            "min_limit": row[6],
            "max_limit": row[7],
            "status": row[8],
            "created_at": row[9]
        })
    return {"orders": orders}

@app.get("/")
def root():
    return {
        "status": "online",
        "commission": f"{COMMISSION*100}%",
        "endpoints": {
            "balance": "/balance/{user_id}",
            "add_balance": "/balance/add/{user_id}",
            "user_stats": "/user/stats/{user_id}",
            "orders": "/orders",
            "create_order": "/orders/create",
            "cancel_order": "/orders/cancel/{order_id}",
            "execute_order": "/orders/execute/{order_id}",
            "user_orders": "/orders/user/{user_id}"
        }
    }
