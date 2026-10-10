# 📷 Гайд по сканированию билетов

## Как работает система билетов?

Каждый билет имеет уникальный QR-код, который содержит UUID (например: `a1b2c3d4-e5f6-7890-abcd-ef1234567890`).

## 3 способа проверить билет

### 1️⃣ Ручной ввод кода (самый простой) ✅

**Для кого:** Админы на входе  
**Что нужно:** Только телефон с Telegram

**Как использовать:**
1. Админ нажимает в боте "✅ Проверить билет"
2. Посетитель показывает билет (QR-код + код под ним)
3. Админ копирует код текстом (он написан под QR)
4. Вставляет в бот
5. Бот проверяет и активирует билет

**Плюсы:**
- Не нужны дополнительные приложения
- Работает всегда
- Быстро

**Минусы:**
- Нужно копировать вручную

---

### 2️⃣ Сканирование QR-кодом в телефоне 📱

**Для кого:** Админы, которые хотят ускорить процесс  
**Что нужно:** Любое приложение для QR (встроено в камеру на iPhone, Google Lens на Android)

**Как использовать:**
1. Админ нажимает "✅ Проверить билет"
2. Открывает приложение для QR
3. Сканирует QR-код билета посетителя
4. Приложение покажет текст (UUID)
5. Копирует и отправляет боту

**Рекомендуемые приложения:**
- iPhone: встроенная Камера (автоматически распознает QR)
- Android: Google Lens или QR Code Reader
- Универсально: Telegram (можно сканировать через @QRbot)

**Плюсы:**
- Быстрее чем ручной ввод
- Меньше ошибок

**Минусы:**
- Нужно переключаться между приложениями

---

### 3️⃣ Веб-сканер (для компьютера) 💻

**Для кого:** Админы на входе с ноутбуком/планшетом  
**Что нужно:** Компьютер с камерой + браузер

**Создайте простую веб-страницу:**

```html
<!DOCTYPE html>
<html>
<head>
    <title>Сканер билетов LEMON</title>
    <script src="https://unpkg.com/html5-qrcode@2.3.8/html5-qrcode.min.js"></script>
    <style>
        body { 
            font-family: Arial; 
            text-align: center; 
            padding: 20px; 
            background: #f5f5f5; 
        }
        #reader { 
            width: 500px; 
            margin: 20px auto; 
            border: 2px solid #333; 
        }
        #result { 
            margin-top: 20px; 
            font-size: 18px; 
            padding: 15px; 
            background: white; 
            border-radius: 8px; 
        }
        .success { color: green; }
        .code { 
            background: #eee; 
            padding: 10px; 
            margin: 10px 0; 
            border-radius: 4px;
            font-family: monospace;
            user-select: all;
        }
    </style>
</head>
<body>
    <h1>🍋 LEMON Tickets - Сканер</h1>
    <div id="reader"></div>
    <div id="result">Наведите камеру на QR-код билета</div>

    <script>
        function onScanSuccess(decodedText) {
            document.getElementById('result').innerHTML = `
                <div class="success">✅ Билет отсканирован!</div>
                <div class="code">${decodedText}</div>
                <small>Скопируйте код и отправьте боту</small>
            `;
            
            // Автокопирование в буфер
            navigator.clipboard.writeText(decodedText);
            
            // Звуковой сигнал
            new Audio('data:audio/wav;base64,UklGRnoGAABXQVZFZm10IBAAAAABAAEAQB8AAEAfAAABAAgAZGF0YQoGAACBhYqFbF1fdJivrJBhNjVgodDbq2EcBj+a2/LDciUFLIHO8tiJNwgZaLvt559NEAxQp+PwtmMcBjiR1/LMeSwFJHfH8N2QQAoUXrTp66hVFApGn+DyvmwhBSuBzvLZiTYIG2m98OScTgwOUKni77RgGwU7k9n1znkpBSh+zPLaizsKGGS56+mmUhELSpvi9L1rIAUsgs/y2Ik3CBtpvfDknE4MDlCp4u+0YBsGPJPZ9c15KQUofs7y24o7ChhkvO3pp1QRDEqb4/O+aiAGL4LQ8tqKOwocab3v5J1ODg9Rq+PysmEbBj2T2vXOeisFKH/P8tyLPAoYZL3t6qdUEQ1Lnef0vmogBi+D0PLai + 24oMBxNyQQAoUXrTo67JXFApGn+DyvmwhBSuBzvLZiTYIG2m98OScTgwOUKni77RgGwU7k9n1znkpBSh/z/LaizsKGGS56+mmUhELSpvi9L1rIAUsgs/y2Ik3CBtpvfDknE4MDlCp4u+0YBsGPJPZ9c15KQUofs7y24o7ChhkvO3pp1QRDEqb4/O+aiAGL4LQ8tqKOwocab3v5J1ODg9Rq+PysmEbBj2T2vXOeisFKH/P8tyLPAoYZL3t6qdUEQ1Lnef0vmogBi+D0PLai').play();
        }

        const html5QrcodeScanner = new Html5QrcodeScanner(
            "reader", 
            { fps: 10, qrbox: 250 }
        );
        html5QrcodeScanner.render(onScanSuccess);
    </script>
</body>
</html>
```

Сохраните как `scanner.html` и откройте в браузере.

**Плюсы:**
- Самый быстрый способ
- Автоматически копирует код
- Звуковое подтверждение
- Можно использовать планшет

**Минусы:**
- Нужен компьютер/планшет с камерой

---

## Мобильное приложение (будущее) 📲

### Планируется разработка:

**Возможности:**
- Встроенный сканер QR
- Прямая интеграция с ботом
- Офлайн режим (кэширование)
- Статистика в реальном времени
- Push-уведомления

**Платформы:**
- iOS (Swift/SwiftUI)
- Android (Kotlin/Jetpack Compose)
- Или кроссплатформа (Flutter/React Native)

---

## Рекомендации для организаторов

### Для маленьких мероприятий (до 50 человек):
- Используйте **ручной ввод** (способ 1)
- Один админ на входе справится

### Для средних мероприятий (50-200 человек):
- Используйте **QR-сканер на телефоне** (способ 2)
- 2-3 админа на входе

### Для больших мероприятий (200+ человек):
- Используйте **веб-сканер** (способ 3)
- Несколько точек входа с планшетами/ноутбуками
- Отдельный админ для решения проблем

---

## Частые проблемы

**❌ QR-код не сканируется:**
- Убедитесь что изображение четкое
- Увеличьте яркость экрана
- Используйте ручной ввод кода

**❌ Билет уже использован:**
- Проверьте дату и время использования
- Возможна попытка повторного входа
- Свяжитесь с администратором

**❌ Билет не найден:**
- Проверьте правильность кода
- Возможно билет был отменен
- Проверьте базу данных

---

## Безопасность

✅ Каждый билет можно использовать только один раз  
✅ UUID невозможно подделать (32 символа)  
✅ В коде записано кто и когда активировал билет  
✅ Админы видят тип билета (куплен/подарен)

---

## Техническая информация

**Формат кода:** UUID v4  
**Пример:** `550e8400-e29b-41d4-a716-446655440000`  
**Длина:** 36 символов  
**Уникальность:** 2^122 возможных вариантов

**Проверка в базе:**
1. Ищем билет по QR-коду
2. Проверяем статус (active/used)
3. Проверяем дату использования
4. Активируем и записываем админа + время
5. Возвращаем информацию о билете
