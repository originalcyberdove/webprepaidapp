import mysql.connector
from flask import Flask, request, jsonify
from datetime import datetime

app = Flask(__name__)

# Database Configuration
db_config = {
    'user': 'root',
    'password': 'cyberhawk..',
    'host': 'localhost',
    'database': 'PrepaidElectricityDB'
}

def get_db_connection():
    return mysql.connector.connect(**db_config)

# ==========================================
# 1. AUTHENTICATION
# ==========================================

@app.route('/api/register', methods=['POST'])
def register_customer():
    data = request.json
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        query = "INSERT INTO Customer (full_name, email, phone, password) VALUES (%s, %s, %s, %s)"
        # Note: In production, hash the password before sending to DB!
        values = (data['full_name'], data['email'], data['phone'], data['password'])
        cursor.execute(query, values)
        conn.commit()
        return jsonify({"message": "Customer registered successfully", "id": cursor.lastrowid}), 201
    except mysql.connector.Error as err:
        return jsonify({"error": str(err)}), 400
    finally:
        cursor.close()
        conn.close()

@app.route('/api/login', methods=['POST'])
def login():
    data = request.json
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    # Simple login logic
    query = "SELECT customer_id, full_name FROM Customer WHERE email = %s AND password = %s"
    cursor.execute(query, (data['email'], data['password']))
    user = cursor.fetchone()
    cursor.close()
    conn.close()
    
    if user:
        return jsonify({"message": "Login successful", "user": user}), 200
    else:
        return jsonify({"message": "Invalid credentials"}), 401

# ==========================================
# 2. CORE BUSINESS LOGIC (BUY TOKEN)
# ==========================================

@app.route('/api/buy-token', methods=['POST'])
def buy_token():
    """
    Calls the MySQL Stored Procedure 'BuyElectricityToken'
    """
    data = request.json
    meter_id = data['meter_id']
    tariff_id = data['tariff_id'] # Usually 1 for Residential
    amount = data['amount']

    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        
        # Call the Stored Procedure created in the SQL step
        # args: (p_meter_id, p_tariff_id, p_amount_paid)
        cursor.callproc('BuyElectricityToken', [meter_id, tariff_id, amount])
        
        # Fetch the results from the stored procedure
        for result in cursor.stored_results():
            purchase_details = result.fetchall()
            
        conn.commit() # Commit the transaction
        
        return jsonify({
            "status": "success",
            "data": purchase_details[0] # Returns Token, Units Added, etc.
        }), 200

    except mysql.connector.Error as err:
        return jsonify({"status": "error", "message": str(err)}), 500
    finally:
        cursor.close()
        conn.close()

# ==========================================
# 3. REPORTING / DASHBOARD
# ==========================================

@app.route('/api/dashboard/<int:customer_id>', methods=['GET'])
def get_dashboard(customer_id):
    """
    Uses the SQL View 'CustomerTransactionHistory'
    """
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    # 1. Get recent transactions
    query_history = """
        SELECT meter_number, purchase_date, amount_paid, generated_token, live_meter_balance
        FROM CustomerTransactionHistory 
        WHERE customer_id = %s 
        ORDER BY purchase_date DESC LIMIT 5
    """
    cursor.execute(query_history, (customer_id,))
    history = cursor.fetchall()
    
    # 2. Get Meters owned by user
    query_meters = "SELECT meter_id, meter_number, current_balance FROM Meter WHERE customer_id = %s"
    cursor.execute(query_meters, (customer_id,))
    meters = cursor.fetchall()

    cursor.close()
    conn.close()
    
    return jsonify({
        "meters": meters,
        "recent_transactions": history
    }), 200

@app.route('/api/consumption/<int:meter_id>', methods=['GET'])
def get_consumption_log(meter_id):
    """
    Returns daily usage for charts
    """
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    query = """
        SELECT DATE(timestamp) as date, SUM(units_used) as total_units
        FROM ConsumptionLog
        WHERE meter_id = %s
        GROUP BY DATE(timestamp)
        ORDER BY date ASC
        LIMIT 30
    """
    cursor.execute(query, (meter_id,))
    logs = cursor.fetchall()
    
    cursor.close()
    conn.close()
    
    # Format dates to string for JSON
    for log in logs:
        log['date'] = log['date'].strftime('%Y-%m-%d')
        log['total_units'] = float(log['total_units'])

    return jsonify(logs), 200

if __name__ == '__main__':
    app.run(debug=True, port=5000)