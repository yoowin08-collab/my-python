# Python 3.11 Slim version ကို base image အဖြစ် သုံးထားပါတယ် (Size သေးပြီး မြန်စေဖို့)
FROM python:3.11-slim

# Working directory သတ်မှတ်ခြင်း
WORKDIR /app

# System dependencies များကို Install လုပ်ခြင်း (asyncpg / psycopg2 အတွက် လိုအပ်သော build tools များ)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# requirements.txt ကို အရင် copy ကူးပြီး Python packages များ install လုပ်ခြင်း (Cache မိအောင်လို့ပါ)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Project ရဲ့ Code အားလုံးကို Copy ကူးယူခြင်း
COPY . .

# Bot ကို စတင် run မည့် Command
CMD ["python", "bot.py"]
