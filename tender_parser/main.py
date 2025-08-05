import argparse
import csv
import sqlite3
import time
import random
import logging
import os  # Добавлен импорт модуля os
from bs4 import BeautifulSoup
from typing import List, Dict
from urllib.parse import urljoin
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.common.exceptions import TimeoutException, WebDriverException, NoSuchElementException
from webdriver_manager.chrome import ChromeDriverManager

# Настройка логирования
logging.basicConfig(
    filename='tender_parser.log',
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Глобальные настройки таймаутов
PAGE_LOAD_TIMEOUT = 240  # 4 минуты на загрузку страницы
ELEMENT_TIMEOUT = 90  # 90 секунд на появление элементов
ATTEMPT_TIMEOUT = 1800  # 30 минут на общую попытку
RETRY_DELAY = 20  # 20 секунд между попытками
MAX_DRIVER_RESTARTS = 5  # Максимальное количество перезапусков драйвера


def create_driver() -> webdriver.Chrome:
    """Создает и настраивает экземпляр Chrome WebDriver"""
    chrome_options = Options()
    chrome_options.add_argument("--headless=new")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.add_argument("--disable-webgl")
    chrome_options.add_argument("--disable-software-rasterizer")
    chrome_options.add_argument("--disable-extensions")
    chrome_options.add_argument("--log-level=3")
    chrome_options.add_argument("--ignore-certificate-errors")
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
    chrome_options.add_experimental_option('useAutomationExtension', False)

    # Решение проблем с VoiceTranscription
    chrome_options.add_argument("--disable-features=VoiceTranscription")
    chrome_options.add_argument("--disable-features=EnableDrDc")

    chrome_options.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/116.0.0.0 Safari/537.36"
    )

    # Решение проблем с таймаутом
    service = Service(
        ChromeDriverManager().install(),
        service_args=['--verbose'],
        log_path=os.devnull  # Отключаем логи драйвера
    )

    driver = webdriver.Chrome(service=service, options=chrome_options)
    driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
    driver.set_page_load_timeout(PAGE_LOAD_TIMEOUT)
    driver.set_script_timeout(30)
    return driver


def fetch_tenders(max_tenders: int) -> List[Dict]:
    """Получает список тендеров с использованием Selenium"""
    tenders = []
    base_url = "https://rostender.info"
    driver_restarts = 0
    driver = None

    try:
        driver = create_driver()
        page = 1
        collected = 0
        consecutive_empty = 0
        start_time = time.time()

        while collected < max_tenders and consecutive_empty < 3:
            # Проверка общего времени выполнения
            if time.time() - start_time > ATTEMPT_TIMEOUT:
                logger.warning(f"Превышено общее время выполнения ({ATTEMPT_TIMEOUT} сек)")
                print(f"Превышено общее время выполнения ({ATTEMPT_TIMEOUT} сек)")
                break

            url = f"https://rostender.info/extsearch?page={page}"
            logger.info(f"Загрузка страницы {page}: {url}")
            print(f"Загрузка страницы {page}: {url}")

            # Загрузка страницы с повторными попытками
            loaded = False
            for attempt in range(3):
                try:
                    driver.get(url)

                    # Явное ожидание готовности страницы
                    WebDriverWait(driver, 30).until(
                        lambda d: d.execute_script("return document.readyState") == "complete"
                    )
                    loaded = True
                    break

                except (TimeoutException, WebDriverException) as e:
                    logger.error(f"Ошибка загрузки: {type(e).__name__} - {str(e)[:200]}")
                    print(f"Ошибка загрузки: {type(e).__name__} - {str(e)[:200]}")

                    if attempt < 2:
                        delay = RETRY_DELAY * (attempt + 1)
                        logger.info(f"Повторная попытка через {delay} сек")
                        print(f"Повторная попытка через {delay} сек")
                        time.sleep(delay)
                    else:
                        logger.warning("Не удалось загрузить страницу после 3 попыток")
                        print("Не удалось загрузить страницу после 3 попыток")

                        # Перезапуск драйвера при критической ошибке
                        if driver_restarts < MAX_DRIVER_RESTARTS:
                            logger.info("Попытка перезапуска драйвера")
                            print("Попытка перезапуска драйвера")
                            try:
                                driver.quit()
                            except:
                                pass

                            driver = create_driver()
                            driver_restarts += 1
                            logger.info(f"Драйвер перезапущен ({driver_restarts}/{MAX_DRIVER_RESTARTS})")
                            print(f"Драйвер перезапущен ({driver_restarts}/{MAX_DRIVER_RESTARTS})")
                        else:
                            logger.error("Достигнут лимит перезапусков драйвера")
                            print("Достигнут лимит перезапусков драйвера")
                            loaded = False
                            break

            if not loaded:
                consecutive_empty += 1
                page += 1
                continue

            # Прокрутка страницы для загрузки всех элементов
            try:
                last_height = driver.execute_script("return document.body.scrollHeight")
                for _ in range(3):
                    driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                    time.sleep(1.5)
                    new_height = driver.execute_script("return document.body.scrollHeight")
                    if new_height == last_height:
                        break
                    last_height = new_height
            except Exception as e:
                logger.error(f"Ошибка прокрутки: {str(e)[:100]}")
                print(f"Ошибка прокрутки: {str(e)[:100]}")

            # Парсинг страницы
            try:
                soup = BeautifulSoup(driver.page_source, 'html.parser')
            except Exception as e:
                logger.error(f"Ошибка парсинга HTML: {str(e)[:100]}")
                print(f"Ошибка парсинга HTML: {str(e)[:100]}")
                consecutive_empty += 1
                page += 1
                continue

            # Проверка на отсутствие результатов
            no_results = soup.find('div', string=lambda text: text and 'Не найдено ни одного тендера' in text)
            if no_results:
                logger.info(f"На странице {page} нет тендеров")
                print(f"На странице {page} нет тендеров")
                consecutive_empty += 1
                page += 1
                continue

            tender_cards = soup.select('article.tender-row')
            logger.info(f"На странице {page} найдено карточек: {len(tender_cards)}")
            print(f"На странице {page} найдено карточек: {len(tender_cards)}")

            if not tender_cards:
                logger.info(f"На странице {page} не найдено карточек тендеров")
                print(f"На странице {page} не найдено карточек тендеров")
                consecutive_empty += 1
                page += 1
                continue
            else:
                consecutive_empty = 0

            # Парсинг карточек тендеров
            for card in tender_cards:
                if collected >= max_tenders:
                    break

                try:
                    title_elem = card.select_one('a.tender-info__description')
                    title = title_elem.text.strip() if title_elem else "Без названия"
                    link = urljoin(base_url, title_elem['href']) if title_elem else "#"

                    tender_id = link.split('/')[-1].split('-')[0] if link != "#" else "N/A"

                    number_elem = card.select_one('span.tender__number')
                    tender_number = number_elem.text.strip() if number_elem else "N/A"

                    price_elem = card.select_one('div.starting-price__price')
                    price = price_elem.text.strip() if price_elem else "Цена не указана"

                    date_elem = card.select_one('span.tender__countdown-text')
                    date = date_elem.text.strip() if date_elem else "N/A"

                    company_elem = card.select_one('div.tender-customer-branches a')
                    company = company_elem.text.strip() if company_elem else "Компания не указана"

                    region_elem = card.select_one('div.tender-address')
                    region = region_elem.text.strip() if region_elem else "Регион не указан"

                    # Проверка на дубликаты
                    if not any(t['id'] == tender_id for t in tenders):
                        tenders.append({
                            'id': tender_id,
                            'number': tender_number,
                            'title': title,
                            'link': link,
                            'company': company,
                            'price': price,
                            'date': date,
                            'region': region
                        })
                        collected += 1
                        msg = f"Добавлен тендер {collected}/{max_tenders}: {tender_id} - {title[:30]}..."
                        print(msg)
                        logger.info(msg)
                except Exception as e:
                    error_msg = f"Ошибка при парсинге карточки: {str(e)[:100]}"
                    print(error_msg)
                    logger.error(error_msg)

            # Улучшенный поиск кнопки следующей страницы
            next_found = False
            try:
                # Попробуем несколько стратегий поиска кнопки
                selectors = [
                    'a[aria-label="Next page"]',  # Основной селектор
                    'a[rel="next"]',  # Альтернативный селектор
                    'li.page-item:not(.disabled) a.page-link',  # Общий селектор пагинации
                    'a.page-link:contains("Следующая")',  # По тексту
                    'a.page-link:contains("›")'  # Иконка стрелки
                ]

                for selector in selectors:
                    try:
                        next_btn = driver.find_element(By.CSS_SELECTOR, selector)
                        if next_btn.is_displayed() and "disabled" not in next_btn.get_attribute("class"):
                            next_found = True
                            logger.info(f"Кнопка следующей страницы найдена с селектором: {selector}")
                            print(f"Кнопка следующей страницы найдена с селектором: {selector}")
                            break
                    except NoSuchElementException:
                        continue

                if not next_found:
                    logger.info("Кнопка следующей страницы не найдена ни по одному селектору")
                    print("Кнопка следующей страницы не найдена ни по одному селектору")
            except Exception as e:
                logger.error(f"Ошибка поиска кнопки: {str(e)[:100]}")
                print(f"Ошибка поиска кнопки: {str(e)[:100]}")

            # Если кнопка не найдена, но мы не достигли лимита, попробуем следующую страницу
            if not next_found:
                if collected < max_tenders:
                    logger.info("Попытка перейти на следующую страницу без кнопки")
                    print("Попытка перейти на следующую страницу без кнопки")
                    page += 1
                    continue
                else:
                    logger.info("Достигнут лимит сбора, завершение")
                    print("Достигнут лимит сбора, завершение")
                    break

            page += 1
            delay = random.uniform(15, 30)  # Увеличена задержка
            logger.info(f"Задержка перед следующей страницей: {delay:.1f} сек")
            print(f"Задержка перед следующей страницей: {delay:.1f} сек")
            time.sleep(delay)

    except Exception as e:
        logger.critical(f"Критическая ошибка: {str(e)[:200]}")
        print(f"Критическая ошибка: {str(e)[:200]}")
    finally:
        if driver:
            try:
                driver.quit()
                logger.info("Браузер успешно закрыт")
                print("Браузер успешно закрыт")
            except Exception as e:
                logger.error(f"Ошибка закрытия браузера: {str(e)[:100]}")
                print(f"Ошибка закрытия браузера: {str(e)[:100]}")

    return tenders


def save_to_csv(tenders: List[Dict], filename: str):
    """Сохраняет данные в CSV файл"""
    if not tenders:
        print("Нет данных для сохранения")
        return

    with open(filename, 'w', newline='', encoding='utf-8-sig') as f:
        fieldnames = ['id', 'number', 'title', 'link', 'company', 'price', 'date', 'region']
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(tenders)
        print(f"Сохранено {len(tenders)} тендеров в {filename}")


def save_to_sqlite(tenders: List[Dict], filename: str):
    """Сохраняет данные в базу SQLite"""
    if not tenders:
        print("Нет данных для сохранения")
        return

    conn = sqlite3.connect(filename)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS tenders
                 (id TEXT, number TEXT, title TEXT, link TEXT, 
                  company TEXT, price TEXT, date TEXT, region TEXT)''')

    for tender in tenders:
        c.execute("INSERT INTO tenders VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                  (tender['id'], tender['number'], tender['title'],
                   tender['link'], tender['company'], tender['price'],
                   tender['date'], tender['region']))
    conn.commit()
    conn.close()
    print(f"Сохранено {len(tenders)} тендеров в {filename}")


def main():
    parser = argparse.ArgumentParser(description='Парсер тендеров с rostender.info')
    parser.add_argument('--max', type=int, default=100, help='Количество тендеров')
    parser.add_argument('--output', type=str, required=True, help='Файл для вывода (CSV или SQLite)')
    args = parser.parse_args()

    tenders = fetch_tenders(args.max)

    if tenders:
        if args.output.endswith('.csv'):
            save_to_csv(tenders, args.output)
        elif args.output.endswith('.db'):
            save_to_sqlite(tenders, args.output)
        else:
            print("Неподдерживаемый формат файла. Используйте .csv или .db")
    else:
        print("Не удалось получить данные о тендерах")


if __name__ == '__main__':
    main()