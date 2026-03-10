import mysql.connector
from mysql.connector import Error
from config import DB_CONFIG


def get_connection():
    return mysql.connector.connect(**DB_CONFIG)


def test_connection():
    try:
        conn = get_connection()
        conn.close()
        return True, 'Подключение к БД успешно.'
    except Error as exc:
        return False, str(exc)
