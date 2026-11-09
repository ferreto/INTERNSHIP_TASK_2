# Берем облегченный образ Python на базе Debian
FROM python:3.11-slim

# Устанавливаем Apache, инструменты для сборки mod_wsgi, драйверы для PostgreSQL
# и FFmpeg для обработки видео с эффектом зума
RUN apt-get update && apt-get install -y \
    apache2 \
    apache2-dev \
    libpq-dev \
    gcc \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Устанавливаем рабочую директорию внутри контейнера
WORKDIR /app

# Сначала копируем только requirements.txt (для кэширования слоев Docker)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копируем все остальные файлы проекта в контейнер (включая apply_zoom.py)
COPY . .

# ВАЖНО: Генерируем конфигурацию mod_wsgi и добавляем её в основной конфиг Apache
RUN mod_wsgi-express module-config >> /etc/apache2/apache2.conf

# Убираем предупреждение о ServerName
RUN echo "ServerName localhost" >> /etc/apache2/apache2.conf

# Отключаем дефолтный сайт Apache и подключаем наш кастомный конфиг
RUN a2dissite 000-default.conf
COPY apache-config.conf /etc/apache2/sites-available/web_service.conf
RUN a2ensite web_service.conf

# Создаем папку uploads и даем права пользователю www-data (от имени которого работает Apache),
# чтобы сервер мог сохранять оригинальные и обработанные видео
RUN mkdir -p /app/uploads && chown -R www-data:www-data /app/uploads

# Открываем 80-й порт (наружу он будет проброшен на 8000 в docker-compose)
EXPOSE 80

# Запускаем Apache в форграунде (чтобы контейнер не завершал работу)
CMD ["apache2ctl", "-D", "FOREGROUND"]