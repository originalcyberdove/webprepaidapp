# app.py
from flask import Flask, request, jsonify
from flask_cors import CORS
import mysql.connector
from datetime import datetime

app = Flask(__name__)
CORS(app)  # allow your frontend to call this API (restrict origins for production)

# -----------------------
# Database Configuration
# -----------------------
db_config = {
    'user': 'root',
    'password': 'olamide123',
    'host': 'localhost',
    'database': 'PrepaidElectricityDB'
}

def get_db_connection():
    return mysql.connector.connect(**db_config)

# -----------------------
# Helpers
# -----------------------
def safe_close(cursor, conn):
    try:
        if cursor: cursor.close()
    except: pass
    try:
        if conn: conn.close()
    except: pass

# -----------------------
# 1) Authentication
# -----------------------
@app.route('/api/register', methods=['POST'])
def register_customer():
    data = request.json or {}
    required = ['full_name', 'email', 'phone', 'password']
    if not all(k in data and data[k] for k in required):
        return jsonify({"error": "Missing required fields"}), 400

    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        sql = "INSERT INTO Customer (full_name, email, phone, password) VALUES (%s, %s, %s, %s)"
        cursor.execute(sql, (data['full_name'], data['email'], data['phone'], data['password']))
        conn.commit()
        return jsonify({"message": "Customer registered successfully", "id": cursor.lastrowid}), 201
    except mysql.connector.IntegrityError as ie:
        return jsonify({"error": "Integrity error: " + str(ie)}), 400
    except mysql.connector.Error as err:
        return jsonify({"error": str(err)}), 500
    finally:
        safe_close(cursor, conn)

@app.route('/api/login', methods=['POST'])
def login():
    data = request.json or {}
    if 'email' not in data or 'password' not in data:
        return jsonify({"message": "Missing email or password"}), 400

    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        sql = "SELECT customer_id, full_name, email FROM Customer WHERE email = %s AND password = %s"
        cursor.execute(sql, (data['email'], data['password']))
        user = cursor.fetchone()
        if user:
            return jsonify({"message": "Login successful", "user": user}), 200
        else:
            return jsonify({"message": "Invalid credentials"}), 401
    except mysql.connector.Error as err:
        return jsonify({"error": str(err)}), 500
    finally:
        safe_close(cursor, conn)

# -----------------------
# 2) Add Meter
# -----------------------
@app.route('/api/add-meter', methods=['POST'])
def add_meter():
    data = request.json or {}
    required = ['customer_id', 'meter_number', 'meter_type']
    if not all(k in data and data[k] for k in required):
        return jsonify({"error": "Missing customer_id, meter_number or meter_type"}), 400

    customer_id = data['customer_id']
    meter_number = data['meter_number'].strip()
    meter_type = data['meter_type'].strip()
    installation_address = data.get('installation_address', None)

    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        # ensure unique meter_number (db also enforces UNIQUE)
        check_sql = "SELECT meter_id FROM Meter WHERE meter_number = %s"
        cursor.execute(check_sql, (meter_number,))
        if cursor.fetchone():
            return jsonify({"error": "Meter number already exists"}), 400

        insert_sql = """
            INSERT INTO Meter (customer_id, meter_number, meter_type, installation_address, current_balance)
            VALUES (%s, %s, %s, %s, %s)
        """
        cursor.execute(insert_sql, (customer_id, meter_number, meter_type, installation_address, 0.0000))
        conn.commit()
        new_id = cursor.lastrowid

        # return newly created meter row
        safe_close(cursor, None)
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT meter_id, meter_number, meter_type, installation_address, current_balance FROM Meter WHERE meter_id = %s", (new_id,))
        new_meter = cursor.fetchone()
        return jsonify({"message": "Meter added", "meter": new_meter}), 201
    except mysql.connector.Error as err:
        try: conn.rollback()
        except: pass
        return jsonify({"error": str(err)}), 500
    finally:
        safe_close(cursor, conn)

# -----------------------
# 3) Buy Token (stored procedure)
# -----------------------
@app.route('/api/buy-token', methods=['POST'])
def buy_token():
    data = request.json or {}
    # expected: meter_id, tariff_id, amount
    if 'meter_id' not in data or 'amount' not in data:
        return jsonify({"status": "error", "message": "Missing meter_id or amount"}), 400

    meter_id = data['meter_id']
    tariff_id = data.get('tariff_id', 1)
    amount = data['amount']

    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        # call stored procedure BuyElectricityToken(p_meter_id, p_tariff_id, p_amount_paid)
        cursor.callproc('BuyElectricityToken', [meter_id, tariff_id, amount])

        purchase_details = None
        # fetch any result sets returned by the stored procedure
        for result in cursor.stored_results():
            purchase_details = result.fetchall()

        conn.commit()

        if not purchase_details or len(purchase_details) == 0:
            return jsonify({"status": "error", "message": "No purchase details returned"}), 500

        # stored proc returns columns: MeterID, Token, UnitsAdded, NetAmountUsed, Status
        pd = purchase_details[0]
        return jsonify({"status": "success", "data": pd}), 200

    except mysql.connector.Error as err:
        try: conn.rollback()
        except: pass
        return jsonify({"status": "error", "message": str(err)}), 500
    finally:
        safe_close(cursor, conn)

# -----------------------
# 4) Dashboard & Consumption
# -----------------------
@app.route('/api/dashboard/<int:customer_id>', methods=['GET'])
def get_dashboard(customer_id):
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        # recent transactions view (CustomerTransactionHistory) returns purchase records
        cursor.execute("""
            SELECT meter_number, tariff_description, purchase_date, amount_paid, units_purchased, generated_token, live_meter_balance
            FROM CustomerTransactionHistory
            WHERE customer_id = %s
            ORDER BY purchase_date DESC
            LIMIT 10
        """, (customer_id,))
        history = cursor.fetchall()

        cursor.execute("SELECT meter_id, meter_number, meter_type, installation_address, current_balance FROM Meter WHERE customer_id = %s", (customer_id,))
        meters = cursor.fetchall()

        # normalize history fields to names front-end expects
        formatted_history = []
        for h in history:
            formatted_history.append({
                "purchase_date": h.get("purchase_date").strftime('%Y-%m-%d %H:%M:%S') if isinstance(h.get("purchase_date"), datetime) else h.get("purchase_date"),
                "meter_number": h.get("meter_number"),
                "generated_token": h.get("generated_token"),
                "amount_paid": float(h.get("amount_paid") or 0),
                "units_purchased": float(h.get("units_purchased") or 0),
                "live_meter_balance": float(h.get("live_meter_balance") or 0),
                "tariff_description": h.get("tariff_description")
            })

        # format meters current_balance numeric
        for m in meters:
            m['current_balance'] = float(m.get('current_balance') or 0)

        return jsonify({"meters": meters, "recent_transactions": formatted_history}), 200

    except mysql.connector.Error as err:
        return jsonify({"error": str(err)}), 500
    finally:
        safe_close(cursor, conn)

@app.route('/api/consumption/<int:meter_id>', methods=['GET'])
def get_consumption_log(meter_id):
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("""
            SELECT DATE(timestamp) as date, SUM(units_used) as total_units
            FROM ConsumptionLog
            WHERE meter_id = %s
            GROUP BY DATE(timestamp)
            ORDER BY date ASC
            LIMIT 30
        """, (meter_id,))
        logs = cursor.fetchall()
        # format
        for log in logs:
            # log['date'] may be a date or string
            try:
                if hasattr(log['date'], 'strftime'):
                    log['date'] = log['date'].strftime('%Y-%m-%d')
            except:
                pass
            log['total_units'] = float(log['total_units'] or 0)
        return jsonify(logs), 200
    except mysql.connector.Error as err:
        return jsonify({"error": str(err)}), 500
    finally:
        safe_close(cursor, conn)

# -----------------------
# Run
# -----------------------
if __name__ == '__main__':
    app.run(debug=True, port=5000)
