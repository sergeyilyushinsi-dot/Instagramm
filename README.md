# Instagram-агент

Python-бот на Claude, который ведёт экспертный блог с личной частью: обрабатывает фото и видео,
генерирует карусели, пишет тексты, составляет контент-план, анализирует спрос аудитории,
публикует по расписанию и готовит ответы на комментарии. Работает сам в GitHub Actions — раз в час.

**По умолчанию ничего не публикуется без твоего одобрения.**

## Как это работает

```
content/inbox/        ← кидаешь сюда фото/видео (папка с несколькими фото = карусель)
      │  inbox: кадрирование 4:5 / 9:16, автокоррекция, перекодирование Reels,
      │         Claude «смотрит» кадры → формат, рубрика, текст, риски приватности
      ▼
content/queue/*.yaml  ← карточки постов: idea → draft → approved → published
      │  ты меняешь status: draft → approved (можно в приложении GitHub)
      ▼
publish              → загрузка медиа в хранилище → Instagram API → content/published/
```

| Команда | Что делает | Когда запускается сама |
|---|---|---|
| `python -m igagent inbox` | обработать новые фото/видео из `content/inbox` | каждый час и при push |
| `python -m igagent plan` | контент-план на неделю → идеи в очереди + `reports/*-plan.md` | вс 10:00 |
| `python -m igagent write` | тексты для идей; экспертные карусели без фото — генерирует слайды | 10:00 и 18:00 |
| `python -m igagent publish` | опубликовать одобренное, время которого пришло | каждый час |
| `python -m igagent analyze` | статистика + анализ комментариев + тренды ниши → `reports/*-analytics.md` | 07:00 |
| `python -m igagent comments` | черновики ответов в `content/replies.yaml`, отправка одобренных | каждый час |
| `python -m igagent status` | сводка очереди → `reports/queue.md` | каждый час |

Время — по `timezone` из `config/settings.yaml`.

## Как одобрять

- **Пост:** открой файл в `content/queue/`, проверь `caption`, `hashtags`, `notes`
  (там предупреждения о качестве и приватности), поменяй `status: draft` на `status: approved`.
  Ничего не нравится — `status: skipped`.
- **Медиа к идее из плана:** положи фото/видео в папку `content/inbox/<id-поста>/` —
  агент прикрепит их к этой карточке и перепишет текст с учётом кадров.
- **Ответ на комментарий:** в `content/replies.yaml` поставь `approved: true` (текст можно поправить).

## Настройка

### 1. Профиль
Заполни `config/profile.yaml` — ниша, аудитория, голос, рубрики, 2–3 примера своих подписей.
От этого файла зависит всё качество. В `config/settings.yaml` — слоты публикаций и режим одобрения.

### 2. Instagram API
1. Переведи аккаунт в **профессиональный** (Автор или Бизнес): Настройки → Тип аккаунта.
2. На [developers.facebook.com](https://developers.facebook.com/) создай приложение типа «Business»,
   добавь продукт **Instagram → API setup with Instagram login**.
3. Добавь свой аккаунт и сгенерируй токен с правами
   `instagram_business_basic`, `instagram_business_content_publish`,
   `instagram_business_manage_comments`, `instagram_business_manage_insights`.
4. Сохрани `IG_USER_ID` и долгоживущий `IG_ACCESS_TOKEN` (60 дней; продлевается автоматически, см. ниже).

Для своего аккаунта приложение может оставаться в режиме разработки (добавь себя как Instagram-тестировщика) — проходить App Review не нужно.

### 3. Хранилище медиа
Instagram API забирает фото/видео только по публичной ссылке. Проще всего — **Cloudflare R2**
(бесплатно до 10 ГБ): создай бакет, включи Public access (`r2.dev`), создай API-токен с правом записи.
Подойдёт и любой S3.

### 4. Claude
Ключ API на [console.anthropic.com](https://console.anthropic.com/) → `ANTHROPIC_API_KEY`.
Модель и уровень усилий — в `config/settings.yaml`.

### 5. GitHub Actions
Settings → Secrets and variables → Actions → добавь секреты из `.env.example`.
Для автопродления токена Instagram добавь `GH_PAT` — fine-grained token с правом
**Secrets: Read and write** на этот репозиторий (без него продлевай вручную раз в 60 дней:
`python -m igagent refresh-token`).

Workflow работает с веткой `main`. Видео тяжёлые — если ролики больше 50 МБ, включи Git LFS:
`git lfs track "*.mp4" "*.mov"`.

### Локальный запуск
```bash
pip install -r requirements.txt   # + ffmpeg в системе
cp .env.example .env              # заполни ключи
python -m igagent inbox
```

## Режим без ключа Claude

Если ключа `ANTHROPIC_API_KEY` нет, агент работает в «ручном» режиме: GitHub Actions собирает статистику,
прикрепляет фото к карточкам и публикует одобренное, а контент-план, тексты и разбор статистики
делает Claude в сессии Claude Code — просто попроси «сделай план на неделю» или «напиши пост про …».

## Что важно знать

- **Генерация изображений.** Claude анализирует фото и видео, но не рисует картинки. Агент сам делает
  текстовые карусели (`igagent/slides.py`, цвета — `slides:` в settings.yaml, свой шрифт —
  `config/brand/font-bold.ttf`). Для AI-фото можно подключить отдельный генератор.
- **Правила Instagram:** не больше 50 публикаций через API в сутки; Reels — 3–90 с;
  карусель — до 10 элементов. Музыку из библиотеки Instagram через API добавить нельзя.
- **Тексты с `[УТОЧНИТЬ: ...]`** — агент не знает факта и не стал выдумывать. Допиши перед одобрением.
- **Стоимость Claude** — ориентировочно единицы долларов в месяц при 4 постах в неделю (проверь в Console после первой недели); дороже всего `analyze`
  с веб-поиском (можно выключить `analytics.use_web_search`).
