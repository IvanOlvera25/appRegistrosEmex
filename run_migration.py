#!/usr/bin/env python3
"""
Script de migración manual para agregar FuelPurchase y fuel_purchase_id
Ejecutar con: python3 run_migration.py
"""

import os
import sys
import pymysql
from urllib.parse import urlparse
from dotenv import load_dotenv

# Cargar variables de entorno
load_dotenv()

def parse_database_url(url):
    """Parsear la URL de la base de datos"""
    parsed = urlparse(url)
    return {
        'host': parsed.hostname,
        'port': parsed.port or 3306,
        'user': parsed.username,
        'password': parsed.password,
        'database': parsed.path.lstrip('/').split('?')[0],
        'charset': 'utf8mb4'
    }

def run_migration():
    """Ejecutar la migración"""
    print("🚀 Iniciando migración de base de datos...")
    
    # Obtener URL de la base de datos
    database_url = os.getenv('DATABASE_URL')
    if not database_url:
        print("❌ Error: No se encontró DATABASE_URL en el archivo .env")
        sys.exit(1)
    
    print(f"📊 Conectando a la base de datos...")
    
    # Parsear credenciales
    db_config = parse_database_url(database_url)
    
    try:
        # Conectar a la base de datos
        connection = pymysql.connect(**db_config)
        cursor = connection.cursor()
        
        print("✅ Conexión exitosa")
        
        # Lista de comandos SQL
        migrations = [
            # 1. Crear tabla fuel_purchases
            """
            CREATE TABLE IF NOT EXISTS fuel_purchases (
                id INT AUTO_INCREMENT PRIMARY KEY,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                provider VARCHAR(255),
                invoice VARCHAR(100),
                liters_bought DECIMAL(10, 2) NOT NULL,
                price_per_liter DECIMAL(10, 2) NOT NULL,
                total_cost DECIMAL(10, 2) NOT NULL,
                liters_dispersed DECIMAL(10, 2) DEFAULT 0,
                registered_by_id INT,
                project_id INT,
                INDEX idx_created_at (created_at),
                INDEX idx_registered_by (registered_by_id),
                INDEX idx_project (project_id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """,
            
            # 2. Verificar si la columna ya existe antes de agregarla
            """
            SELECT COUNT(*) 
            FROM information_schema.COLUMNS 
            WHERE TABLE_SCHEMA = DATABASE() 
            AND TABLE_NAME = 'operator_logs' 
            AND COLUMN_NAME = 'fuel_purchase_id'
            """,
        ]
        
        # Ejecutar creación de tabla
        print("📝 Creando tabla fuel_purchases...")
        cursor.execute(migrations[0])
        print("✅ Tabla fuel_purchases creada")
        
        # Verificar si la columna existe
        cursor.execute(migrations[1])
        column_exists = cursor.fetchone()[0] > 0
        
        if not column_exists:
            print("📝 Agregando columna fuel_purchase_id a operator_logs...")
            cursor.execute("""
                ALTER TABLE operator_logs 
                ADD COLUMN fuel_purchase_id INT DEFAULT NULL AFTER fuel_liters
            """)
            print("✅ Columna fuel_purchase_id agregada")
            
            # Crear índice
            print("📝 Creando índice idx_fuel_purchase_id...")
            cursor.execute("""
                CREATE INDEX idx_fuel_purchase_id ON operator_logs(fuel_purchase_id)
            """)
            print("✅ Índice creado")
        else:
            print("ℹ️  La columna fuel_purchase_id ya existe, saltando...")
        
        # Intentar agregar claves foráneas (puede fallar si no existen las tablas referenciadas)
        try:
            print("📝 Agregando claves foráneas...")
            
            # Verificar si ya existe la FK antes de agregarla
            cursor.execute("""
                SELECT COUNT(*) 
                FROM information_schema.TABLE_CONSTRAINTS 
                WHERE CONSTRAINT_SCHEMA = DATABASE() 
                AND TABLE_NAME = 'fuel_purchases' 
                AND CONSTRAINT_NAME = 'fk_fuel_purchases_registered_by'
            """)
            
            if cursor.fetchone()[0] == 0:
                cursor.execute("""
                    ALTER TABLE fuel_purchases 
                    ADD CONSTRAINT fk_fuel_purchases_registered_by 
                        FOREIGN KEY (registered_by_id) 
                        REFERENCES users(id) 
                        ON DELETE SET NULL
                """)
                print("✅ FK fuel_purchases -> users creada")
            
            cursor.execute("""
                SELECT COUNT(*) 
                FROM information_schema.TABLE_CONSTRAINTS 
                WHERE CONSTRAINT_SCHEMA = DATABASE() 
                AND TABLE_NAME = 'fuel_purchases' 
                AND CONSTRAINT_NAME = 'fk_fuel_purchases_project'
            """)
            
            if cursor.fetchone()[0] == 0:
                cursor.execute("""
                    ALTER TABLE fuel_purchases 
                    ADD CONSTRAINT fk_fuel_purchases_project 
                        FOREIGN KEY (project_id) 
                        REFERENCES projects(id) 
                        ON DELETE SET NULL
                """)
                print("✅ FK fuel_purchases -> projects creada")
            
            cursor.execute("""
                SELECT COUNT(*) 
                FROM information_schema.TABLE_CONSTRAINTS 
                WHERE CONSTRAINT_SCHEMA = DATABASE() 
                AND TABLE_NAME = 'operator_logs' 
                AND CONSTRAINT_NAME = 'fk_operator_logs_fuel_purchase'
            """)
            
            if cursor.fetchone()[0] == 0 and not column_exists:
                cursor.execute("""
                    ALTER TABLE operator_logs 
                    ADD CONSTRAINT fk_operator_logs_fuel_purchase 
                        FOREIGN KEY (fuel_purchase_id) 
                        REFERENCES fuel_purchases(id) 
                        ON DELETE SET NULL
                """)
                print("✅ FK operator_logs -> fuel_purchases creada")
                
        except pymysql.err.OperationalError as e:
            print(f"⚠️  Advertencia al crear claves foráneas: {e}")
            print("   (Esto es normal si las tablas referenciadas no existen)")
        
        # Commit de los cambios
        connection.commit()
        
        print("\n🎉 ¡Migración completada exitosamente!")
        print("📌 Ahora puedes reiniciar el servidor Flask")
        
    except pymysql.err.OperationalError as e:
        print(f"\n❌ Error de conexión: {e}")
        print("   Verifica que la URL de la base de datos sea correcta")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Error durante la migración: {e}")
        connection.rollback()
        sys.exit(1)
    finally:
        if 'connection' in locals():
            cursor.close()
            connection.close()
            print("🔌 Conexión cerrada")

if __name__ == "__main__":
    print("\n" + "="*60)
    print("  MIGRACIÓN: Agregar FuelPurchase y fuel_purchase_id")
    print("="*60 + "\n")
    
    # Confirmar con el usuario
    response = input("⚠️  Esta operación modificará la base de datos. ¿Continuar? (s/N): ")
    
    if response.lower() in ['s', 'si', 'sí', 'y', 'yes']:
        run_migration()
    else:
        print("❌ Migración cancelada")
        sys.exit(0)
