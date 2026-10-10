# 🍋 LEMON Tickets

Telegram-бот для продажи и управления билетами на мероприятия.

## Возможности

### Для пользователей:
- 🎫 Просмотр доступных мероприятий
- 💳 Покупка билетов через ЮКасса
- 🎟 QR-билеты с уникальными кодами
- 💬 Техническая поддержка

### Для администраторов:
- ➕ Создание мероприятий
- 📊 Статистика продаж
- ✅ Проверка билетов по QR-коду
- 👥 Управление админами

## Установка

### 1. Клонируйте репозиторий
```bash
git clone <repo-url>
cd lemon-tickets
```

### 2. Установите зависимости
```bash
pip install -r requirements.txt
```

### 3. Настройте окружение
Создайте файл `.env` на основе `.env.example`:
```bash
cp .env.example .env
```

Заполните переменные:
- `BOT_TOKEN` - токен от @BotFather
- `DATABASE_URL` - URL PostgreSQL базы
- `YOOKASSA_SHOP_ID` - ID магазина ЮКасса
- `YOOKASSA_SECRET_KEY` - секретный ключ ЮКасса
- `ADMIN_IDS` - ID главных админов через запятую

### 4. Получение токенов

#### Telegram Bot Token:
1. Напишите @BotFather в Telegram
2. Отправьте `/newbot`
3. Следуйте инструкциям
4. Скопируйте токен

#### ЮКасса:
1. Зарегистрируйтесь на [yookassa.ru](https://yookassa.ru)
2. Создайте магазин
3. В настройках получите `shopId` и `secretKey`

### 5. Запуск локально
```bash
python bot.py
```

## Деплой на Railway

### 1. Создайте проект на Railway
1. Зайдите на [railway.app](https://railway.app)
2. Нажмите "New Project"
3. Выберите "Deploy from GitHub repo"
4. Выберите ваш репозиторий

### 2. Добавьте PostgreSQL
1. В проекте нажмите "New"
2. Выберите "Database" → "PostgreSQL"
3. Скопируйте `DATABASE_URL` из переменных

### 3. Настройте переменные окружения
В настройках проекта добавьте:
- `BOT_TOKEN`
- `DATABASE_URL` (автоматически из PostgreSQL)
- `YOOKASSA_SHOP_ID`
- `YOOKASSA_SECRET_KEY`
- `ADMIN_IDS`

### 4. Настройте запуск
Создайте `Procfile`:
```
web: python bot.py
```

Railway автоматически задеплоит бота.

## Использование

### Команды пользователя:
- `/start` - начало работы с ботом
- 🎫 Мероприятия - список доступных событий
- 🎟 Мои билеты - купленные билеты
- 💬 Поддержка - связь с поддержкой

### Команды администратора:
- ➕ Создать событие - добавление нового мероприятия
- 📊 Статистика - просмотр продаж
- ✅ Проверить билет - валидация QR-кода
- 👥 Добавить админа - добавление нового администратора

## Структура проекта
```
lemon-tickets/
├── bot.py              # Основной файл запуска
├── config.py           # Конфигурация
├── database/           # Работа с БД
│   ├── models.py
│   └── __init__.py
├── handlers/           # Обработчики команд
│   ├── user_handlers.py
│   ├── admin_handlers.py
│   ├── payment_handlers.py
│   └── __init__.py
├── keyboards/          # Клавиатуры
│   ├── user.py
│   └── __init__.py
├── utils/              # Утилиты
│   ├── qr_generator.py
│   ├── payment.py
│   └── __init__.py
├── requirements.txt
├── .env.example
└── README.md
```

## Поддержка

По вопросам: [@your_username](https://t.me/your_username)

## Лицензия

MIT
