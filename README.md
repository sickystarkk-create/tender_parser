# Парсер тендеров с rostender.info

## Описание
Программа для сбора информации о тендерах с сайта rostender.info.

## Требования
- Python 3.8+
- Chrome Browser

## Установка/Использование
```bash
git clone https://github.com/ваш-username/ваш-репозиторий.git
cd ваш-репозиторий
python -m venv .venv
source .venv/bin/activate  # Linux/MacOS
.venv\Scripts\activate    # Windows
pip install -r requirements.txt

## Использование 
python main.py --max 100 --output tenders.csv
python main.py --max 50 --output tenders.db

## Параметры
--max: Количество тендеров (по умолчанию: 100)

--output: Путь к файлу вывода (CSV или SQLite)

## Структура данных
Каждый тендер содержит:

id: Уникальный ID тендера

number: Номер тендера

title: Название тендера

link: Ссылка на тендер

company: Организатор

price: Начальная цена

date: Дата окончания приёма предложений

region: Регион
