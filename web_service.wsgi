import sys
import os

# Добавляем папку проекта в пути поиска Python,
# чтобы Apache смог найти модуль web_service
sys.path.insert(0, os.path.dirname(__file__))

from web_service import app as application