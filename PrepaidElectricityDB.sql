-- =============================================
-- 1. DATABASE CREATION & SETUP
-- =============================================
DROP DATABASE IF EXISTS PrepaidElectricityDB;
CREATE DATABASE PrepaidElectricityDB;
USE PrepaidElectricityDB;

-- =============================================
-- 2. CREATE TABLES
-- =============================================

-- Customer Table
CREATE TABLE Customer (
    customer_id INT AUTO_INCREMENT PRIMARY KEY,
    full_name VARCHAR(100) NOT NULL,
    email VARCHAR(100) NOT NULL UNIQUE,
    phone VARCHAR(20) NOT NULL UNIQUE,
    password VARCHAR(255) NOT NULL
);

-- Tariff Table
CREATE TABLE Tariff (
    tariff_id INT AUTO_INCREMENT PRIMARY KEY,
    rate_per_unit DECIMAL(10, 2) NOT NULL,
    service_charge DECIMAL(10, 2) NOT NULL,
    tariff_description VARCHAR(50)
);

-- Meter Table
-- Added 'current_balance' column here directly for the system logic
CREATE TABLE Meter (
    meter_id INT AUTO_INCREMENT PRIMARY KEY,
    customer_id INT,
    meter_number VARCHAR(50) NOT NULL UNIQUE,
    meter_type VARCHAR(20) NOT NULL,
    installation_address TEXT,
    current_balance DECIMAL(10, 4) DEFAULT 0.0000,
    CONSTRAINT FK_Meter_Customer FOREIGN KEY (customer_id) REFERENCES Customer(customer_id) ON DELETE CASCADE
);

-- TokenPurchase Table
CREATE TABLE TokenPurchase (
    purchase_id INT AUTO_INCREMENT PRIMARY KEY,
    meter_id INT,
    tariff_id INT,
    amount_paid DECIMAL(10, 2) NOT NULL,
    units_purchased DECIMAL(10, 4) NOT NULL,
    generated_token VARCHAR(20) NOT NULL UNIQUE,
    purchase_date DATETIME DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT FK_Purchase_Meter FOREIGN KEY (meter_id) REFERENCES Meter(meter_id),
    CONSTRAINT FK_Purchase_Tariff FOREIGN KEY (tariff_id) REFERENCES Tariff(tariff_id)
);

-- Payment Table
CREATE TABLE Payment (
    payment_id INT AUTO_INCREMENT PRIMARY KEY,
    purchase_id INT UNIQUE,
    payment_date DATETIME DEFAULT CURRENT_TIMESTAMP,
    payment_method VARCHAR(50),
    payment_status VARCHAR(20),
    CONSTRAINT FK_Payment_Purchase FOREIGN KEY (purchase_id) REFERENCES TokenPurchase(purchase_id) ON DELETE CASCADE
);

-- ConsumptionLog Table
CREATE TABLE ConsumptionLog (
    log_id INT AUTO_INCREMENT PRIMARY KEY,
    meter_id INT,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    units_used DECIMAL(10, 4),
    units_remaining DECIMAL(10, 4),
    CONSTRAINT FK_Log_Meter FOREIGN KEY (meter_id) REFERENCES Meter(meter_id)
);

-- =============================================
-- 3. INSERT SAMPLE DATA
-- =============================================

-- Insert Tariffs
INSERT INTO Tariff (rate_per_unit, service_charge, tariff_description) VALUES 
(0.50, 5.00, 'Residential Standard'),
(0.75, 10.00, 'Commercial High-Usage');

-- Insert Customers (Password is plain text for demo: 'hashed_pw_1')
INSERT INTO Customer (full_name, email, phone, password) VALUES 
('John Doe', 'john.doe@example.com', '555-0101', 'hashed_pw_1'),
('Jane Smith', 'jane.smith@example.com', '555-0102', 'hashed_pw_2'),
('Test User', 'test@demo.com', '000-0000', '123456');

-- Insert Meters (Linked to Customers)
INSERT INTO Meter (customer_id, meter_number, meter_type, installation_address, current_balance) VALUES 
(1, 'MTR-1001', 'Single Phase', '123 Maple St', 50.00),
(2, 'MTR-1002', 'Three Phase', '456 Oak Ave', 120.50),
(3, 'MTR-9999', 'Single Phase', 'Demo Lane', 10.00);

-- =============================================
-- 4. STORED PROCEDURES (BUSINESS LOGIC)
-- =============================================

DELIMITER //

CREATE PROCEDURE BuyElectricityToken(
    IN p_meter_id INT,
    IN p_tariff_id INT,
    IN p_amount_paid DECIMAL(10, 2)
)
BEGIN
    DECLARE v_rate DECIMAL(10, 2);
    DECLARE v_service_charge DECIMAL(10, 2);
    DECLARE v_net_amount DECIMAL(10, 2);
    DECLARE v_units DECIMAL(10, 4);
    DECLARE v_token VARCHAR(20);
    
    -- Check Meter
    IF NOT EXISTS (SELECT 1 FROM Meter WHERE meter_id = p_meter_id) THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Error: Meter ID does not exist.';
    END IF;

    -- Get Tariff
    SELECT rate_per_unit, service_charge INTO v_rate, v_service_charge
    FROM Tariff WHERE tariff_id = p_tariff_id;

    -- Calculate
    SET v_net_amount = p_amount_paid - v_service_charge;
    
    IF v_net_amount <= 0 THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Error: Amount insufficient for service charge.';
    END IF;

    SET v_units = v_net_amount / v_rate;

    -- Generate Token (Simple Random)
    SET v_token = CONCAT(
        LPAD(FLOOR(RAND() * 10000), 4, '0'), '-',
        LPAD(FLOOR(RAND() * 10000), 4, '0'), '-',
        LPAD(FLOOR(RAND() * 10000), 4, '0'), '-',
        LPAD(FLOOR(RAND() * 10000), 4, '0')
    );

    -- Insert Transaction
    INSERT INTO TokenPurchase (meter_id, tariff_id, amount_paid, units_purchased, generated_token, purchase_date)
    VALUES (p_meter_id, p_tariff_id, p_amount_paid, v_units, v_token, NOW());

    -- Return Result
    SELECT 
        p_meter_id AS MeterID, 
        v_token AS Token, 
        v_units AS UnitsAdded, 
        v_net_amount AS NetAmountUsed,
        'Purchase Successful' AS Status;
END //

DELIMITER ;

-- =============================================
-- 5. TRIGGERS (AUTOMATION)
-- =============================================

DELIMITER //

-- Trigger 1: Add units to meter when token is purchased
CREATE TRIGGER AfterTokenPurchase
AFTER INSERT ON TokenPurchase
FOR EACH ROW
BEGIN
    UPDATE Meter
    SET current_balance = current_balance + NEW.units_purchased
    WHERE meter_id = NEW.meter_id;
END //

-- Trigger 2: Subtract units when consumption is logged
CREATE TRIGGER BeforeConsumptionLog
BEFORE INSERT ON ConsumptionLog
FOR EACH ROW
BEGIN
    DECLARE v_current_bal DECIMAL(10, 4);

    SELECT current_balance INTO v_current_bal FROM Meter WHERE meter_id = NEW.meter_id;

    IF v_current_bal IS NULL THEN SET v_current_bal = 0; END IF;

    -- Set the snapshot of remaining units for the log
    SET NEW.units_remaining = v_current_bal - NEW.units_used;

    -- Update the wallet
    UPDATE Meter
    SET current_balance = current_balance - NEW.units_used
    WHERE meter_id = NEW.meter_id;
END //

DELIMITER ;

-- =============================================
-- 6. VIEWS (REPORTING)
-- =============================================

CREATE OR REPLACE VIEW CustomerTransactionHistory AS
SELECT 
    c.customer_id,
    c.full_name,
    c.email,
    m.meter_number,
    m.meter_type,
    m.current_balance AS live_meter_balance,
    t.tariff_description,
    tp.purchase_date,
    tp.amount_paid,
    tp.units_purchased,
    tp.generated_token
FROM Customer c
JOIN Meter m ON c.customer_id = m.customer_id
JOIN TokenPurchase tp ON m.meter_id = tp.meter_id
JOIN Tariff t ON tp.tariff_id = t.tariff_id;



-- Simulate a purchase for Meter 1
CALL BuyElectricityToken(1, 1, 50.00);

-- Simulate consumption for Meter 1
INSERT INTO ConsumptionLog (meter_id, timestamp, units_used) VALUES (1, NOW() - INTERVAL 2 DAY, 5.5);
INSERT INTO ConsumptionLog (meter_id, timestamp, units_used) VALUES (1, NOW() - INTERVAL 1 DAY, 4.2);
INSERT INTO ConsumptionLog (meter_id, timestamp, units_used) VALUES (1, NOW(), 3.1);