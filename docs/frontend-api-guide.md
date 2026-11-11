# Руководство по интеграции frontend с Semyzbay Backend

Документ описывает актуальный API backend и предназначен для разработчика frontend.

## 1. Адреса и общие правила

- Production API: `https://api.danaai.kz`
- Локальный API: `http://localhost:8000`
- Префикс API: `/api/v1`
- Production Swagger UI: `https://api.danaai.kz/docs`
- Production OpenAPI JSON: `https://api.danaai.kz/openapi.json`
- Локальный Swagger UI: `http://localhost:8000/docs`
- Проверка процесса: `GET /health`
- Проверка зависимостей: `GET /health/ready`

На frontend адрес рекомендуется хранить в переменной окружения:

```env
NEXT_PUBLIC_API_URL=https://api.danaai.kz
```

Для Vite вместо этого используется, например,
`VITE_API_URL=https://api.danaai.kz`. Production frontend разрешён с origins
`https://danaai.kz` и `https://www.danaai.kz`.

Все защищённые запросы должны содержать access token:

```http
Authorization: Bearer <access_token>
```

JSON-запросы дополнительно содержат:

```http
Content-Type: application/json
```

Для `multipart/form-data` нельзя задавать `Content-Type` вручную: браузер сам добавит
правильный `boundary` при передаче `FormData`.

Каждый ответ содержит заголовок `X-Request-ID`. Его полезно сохранять в логах frontend и
показывать в окне технической ошибки.

## 2. Роли и доступ

Существуют три роли:

| Роль | Назначение |
|---|---|
| `super_admin` | Управление организациями и всеми пользователями; доступ к любому tenant |
| `org_admin` | Пользователи и документы только своей организации |
| `user` | Чат, голосовой агент, RAG, поиск и speech-функции своей организации |

Особенности tenant-доступа:

- `org_admin` и `user` обычно не передают `organization_id`: backend берёт его из токена.
- `super_admin` при работе с поиском, RAG, чатом, голосом и загрузкой документа должен
  передать `organization_id` явно.
- Backend запрещает доступ к чужой организации независимо от данных frontend.
- Если организация или пользователь отключены, login, refresh и любой запрос с текущим
  access token возвращают `401`.

Frontend после `GET /api/v1/auth/me` должен строить меню по `role`, но проверки UI не
заменяют серверную авторизацию.

## 3. Авторизация

### Вход

`POST /api/v1/auth/login`

```json
{
  "email": "user@semyzbay.kz",
  "password": "user-password"
}
```

Ответ:

```json
{
  "access_token": "eyJ...",
  "refresh_token": "eyJ...",
  "token_type": "bearer",
  "expires_in": 1800
}
```

### Текущий пользователь

`GET /api/v1/auth/me`

```json
{
  "id": "uuid",
  "organization_id": "uuid",
  "email": "user@semyzbay.kz",
  "first_name": "Demo",
  "last_name": "User",
  "role": "user",
  "is_active": true,
  "created_at": "2026-10-31T08:00:00Z",
  "updated_at": "2026-10-31T08:00:00Z"
}
```

У `super_admin` поле `organization_id` равно `null`.

### Обновление токенов

`POST /api/v1/auth/refresh`

```json
{
  "refresh_token": "eyJ..."
}
```

Backend использует rotation: после успешного refresh старый refresh token больше не
действует. Нужно атомарно сохранить оба новых токена из ответа.

### Выход

`POST /api/v1/auth/logout`

```json
{
  "refresh_token": "eyJ..."
}
```

Успешный ответ: `204 No Content`. После запроса frontend удаляет оба токена.

### Рекомендуемое поведение API-клиента

1. Добавлять access token ко всем защищённым запросам.
2. При первом `401` один раз вызвать `/auth/refresh`.
3. Сохранить новую пару токенов и повторить исходный запрос.
4. Если refresh тоже вернул `401`, очистить сессию и открыть страницу входа.
5. Не запускать несколько refresh-запросов одновременно: использовать общий promise/lock.

Для браузерного production-приложения предпочтительно хранить refresh token в
`HttpOnly Secure` cookie через BFF/frontend server. Если BFF пока нет, нельзя писать токены
в логи, аналитику или URL.

## 4. Главный пользовательский сценарий: голосовой вопрос

Для основного интерфейса используется один маршрут:

`POST /api/v1/voice/ask`

Формат: `multipart/form-data`.

| Поле | Обязательное | Значение |
|---|---:|---|
| `file` | да | Аудиозапись |
| `response_language` | нет | `kk`, `ru` или `en` |
| `conversation_id` | нет | ID предыдущего диалога. Передавайте его во всех следующих вопросах, чтобы работали уточнения («а если на высоте?») |
| `organization_id` | только для `super_admin` | Организация, в которой выполняется вопрос |

Поддерживаемые форматы: FLAC, MP3, MP4, MPEG, MPGA, M4A, OGG, WAV, WEBM. Максимальный
размер по текущей конфигурации — 25 MB.

Пример:

```ts
type VoiceAnswer = {
  conversation_id: string;
  message_id: string;
  transcript: string;
  answer: string;
  spoken_text: string;
  language: "kk" | "ru" | "en";
  generation_status: "answered" | "insufficient_context" | "failed";
  model: string | null;
  usage: {
    input_tokens: number;
    output_tokens: number;
    reasoning_tokens: number;
  };
  sources: RagSource[];
  citation_validation: {
    valid: boolean;
    citations: string[];
    unknown_citations: string[];
    missing_citations: boolean;
  };
  // Уточняющий вопрос, переписанный с учётом истории диалога; null для первого вопроса.
  standalone_query: string | null;
  audio: {
    url: string;
    content_type: string;
    provider: string;
    model: string;
    voice: string;
    ai_generated: true;
  };
};

async function askByVoice(audio: Blob, accessToken: string): Promise<VoiceAnswer> {
  const form = new FormData();
  form.append("file", audio, "question.webm");
  form.append("response_language", "kk");

  const response = await fetch(`${API_URL}/api/v1/voice/ask`, {
    method: "POST",
    headers: { Authorization: `Bearer ${accessToken}` },
    body: form,
  });

  if (!response.ok) throw await apiError(response);
  return response.json();
}
```

Пример успешного ответа сокращённо:

```json
{
  "conversation_id": "uuid",
  "message_id": "uuid",
  "transcript": "Өрт болған жағдайда не істеу керек?",
  "answer": "... [S1]",
  "spoken_text": "...",
  "language": "kk",
  "generation_status": "answered",
  "model": "gpt-6-luna",
  "usage": {
    "input_tokens": 850,
    "output_tokens": 140,
    "reasoning_tokens": 0
  },
  "sources": [],
  "citation_validation": {
    "valid": true,
    "citations": ["S1"],
    "unknown_citations": [],
    "missing_citations": false
  },
  "audio": {
    "url": "/api/v1/voice/messages/uuid/audio",
    "content_type": "audio/mpeg",
    "provider": "elevenlabs",
    "model": "eleven_v4_turbo",
    "voice": "configured-voice-id",
    "ai_generated": true
  }
}
```

`spoken_text` — точный текст, который backend передал в синтез речи. В отличие от `answer`,
он не содержит Markdown и ссылок вида `[S1]`, которые не должны произноситься голосом.

Если нужно повторно получить текст для уже созданного аудио, используйте тот же маршрут с
параметром `metadata=true`:

```http
GET /api/v1/voice/messages/{message_id}/audio?metadata=true
```

Он возвращает JSON без скачивания MP3:

```json
{
  "message_id": "uuid",
  "spoken_text": "Точный текст, воспроизводимый голосом",
  "audio_url": "/api/v1/voice/messages/uuid/audio",
  "content_type": "audio/mpeg"
}
```

Без `metadata=true` маршрут возвращает бинарный MP3/WAV для воспроизведения.

`audio.url` защищён bearer-токеном, поэтому его нельзя надёжно поставить напрямую в
`<audio src>`. Нужно получить файл через `fetch`, создать Blob URL и освободить его после
использования:

```ts
async function loadProtectedAudio(path: string, accessToken: string): Promise<string> {
  const response = await fetch(`${API_URL}${path}`, {
    headers: { Authorization: `Bearer ${accessToken}` },
  });
  if (!response.ok) throw await apiError(response);
  return URL.createObjectURL(await response.blob());
}

// После проигрывания или unmount:
// URL.revokeObjectURL(audioBlobUrl);
```

В UI нужно явно сообщать, что голос создан ИИ. Backend также возвращает заголовок
`X-AI-Generated-Voice: true`.

Если `generation_status === "insufficient_context"`, это нормальный ответ: утверждённые
документы не содержат достаточной информации. Не показывать его как техническую ошибку.

## 5. Текстовый вопрос и RAG-ответ

`POST /api/v1/chat/messages`

```json
{
  "query": "Какие действия выполнить при пожаре?",
  "response_language": "ru"
}
```

Дополнительные поля:

- `conversation_id` — продолжить существующий диалог;
- `organization_id` — обязательно для `super_admin`, остальным обычно не передавать.

Ответ имеет те же основные поля `ChatResponse`, что и `/voice/ask`, но без `transcript` и
`audio`.

Если `conversation_id` не передать, backend автоматически создаст новый диалог.

**Уточняющие вопросы.** Чтобы ассистент понимал вопросы вроде «а если на высоте?» или
«а для сварщика?», frontend должен передавать `conversation_id` из предыдущего ответа во
всех следующих сообщениях того же диалога. Backend берёт последние сообщения диалога
(по умолчанию 6), переписывает уточнение в самостоятельный вопрос для поиска и показывает
модели короткую историю. Переписанный вопрос возвращается в поле `standalone_query`
(`null`, если переписывать не понадобилось) — его можно показать мелким шрифтом
(«Искал: …») или использовать для отладки. Источником фактов история не является:
ответ по-прежнему опирается только на утверждённые документы и ссылки `[S#]`.

### История, если понадобится позже

- `POST /api/v1/conversations` — создать диалог вручную;
- `GET /api/v1/conversations` — диалоги текущего пользователя;
- `GET /api/v1/conversations/{conversation_id}/messages` — сообщения диалога.

Создание вручную:

```json
{
  "title": "Пожарная безопасность",
  "language": "ru"
}
```

### Потоковый вариант

`POST /api/v1/chat/messages/stream` принимает тот же JSON и возвращает Server-Sent Events
в таком порядке:

| Событие | Данные | Когда |
|---|---|---|
| `status` | `{"stage": "rewriting" \| "retrieving" \| "generating" \| "validating" \| "matching_videos"}` | по ходу работы, сразу после начала запроса |
| `metadata` | `conversation_id`, `message_id`, `model`, `status`, `standalone_query` | ответ готов и проверен |
| `text_delta` | `{"delta": "..."}` | текст ответа частями |
| `completed` | полный `ChatResponse` | последнее событие |
| `error` | `{"status_code": 403, "detail": "..."}` | вместо `metadata`, если запрос не удался |

Этапы `status`: `rewriting` — уточняющий вопрос переписывается с учётом истории (бывает
только в продолжении диалога); `retrieving` — поиск по документам; `generating` — модель
пишет ответ; `validating` — проверка ссылок; `matching_videos` — подбор обучающего видео
(только для ответа со ссылками). Если в документах ничего не найдено, после
`retrieving` сразу приходит `metadata`. Рекомендуемые подписи: «Уточняю вопрос…»,
«Ищу в инструкциях…», «Формирую ответ…», «Проверяю источники…», «Подбираю видео…».
Подобранные видео приходят в поле `videos` события `completed` (в `metadata` их нет).

Поток всегда отвечает HTTP 200, кроме ошибок авторизации и валидации тела запроса (401/422
до начала потока). Ошибки доступа к диалогу, поиска и LLM приходят событием `error` с
исходным `status_code`.

Это POST, поэтому стандартный браузерный `EventSource` не подходит — нужен streaming
`fetch`. Текст ответа отдаётся только после проверки ссылок, поэтому непроверенный вывод
модели клиенту не попадает; события `status` закрывают паузу до появления текста.

## 6. Источники ответа

Тип одного элемента `sources`:

```ts
type RagSource = {
  citation_id: string;            // например S1
  chunk_id: string;
  document_id: string;
  document_version_id: string;
  text: string;
  retrieval_score: number;
  rerank_score: number;
  page_number: number | null;
  section_title: string | null;
  document_title: string | null;
  document_url: string | null;
};
```

Рекомендуемое отображение:

- в тексте ответа оставить маркеры `[S1]`, `[S2]`;
- сделать маркер кликабельным;
- по клику открыть карточку источника с `text`, `page_number`, `section_title`;
- показывать `document_title` и кнопку «Открыть документ» по `document_url`.

`document_url` защищён bearer-токеном, поэтому обычный `<a href>` не передаст авторизацию.
Получите документ через `fetch`, создайте Blob URL и откройте его в новой вкладке:

```ts
async function openRagDocument(documentUrl: string, accessToken: string): Promise<void> {
  const response = await fetch(documentUrl, {
    headers: { Authorization: `Bearer ${accessToken}` },
  });
  if (!response.ok) throw await apiError(response);

  const blobUrl = URL.createObjectURL(await response.blob());
  window.open(blobUrl, "_blank", "noopener,noreferrer");
  window.setTimeout(() => URL.revokeObjectURL(blobUrl), 60_000);
}
```

Обычный `user` может скачать только утверждённый активный документ своей организации.
Неутверждённые, архивные документы и документы другого tenant возвращают `404`.

### Видео рядом с ответом

`ChatResponse` (а значит и `/voice/ask`, и событие `completed` в SSE) содержит поле
`videos` — утверждённые обучающие ролики, иллюстрирующие процитированные инструкции.
Обычно это 0 или 1 ролик. Видео не является источником фактов и не получает маркер
`[S#]`: показывайте его после текста ответа, отдельной карточкой.

```ts
type VideoSuggestion = {
  id: string;
  title: string;
  description: string;
  duration_seconds: number | null;
  width: number | null;
  height: number | null;
  mime_type: string;             // "video/mp4"
  stream_url: string;            // относительный путь с подписанным token
  thumbnail_url: string | null;  // тоже с token
  expires_at: string;            // ISO-время, когда ссылки перестанут работать
  score: number;                 // похожесть вопроса на карточку видео, 0..1
  linked_document_ids: string[]; // процитированные инструкции, к которым относится ролик
};
```

Ролик показывается, только если одновременно:

1. ответ имеет статус `answered` (не «недостаточно информации», не small talk);
2. в ответе процитирована инструкция, к которой администратор привязал ролик;
3. вопрос достаточно похож на карточку ролика (название, описание, примеры вопросов).

`stream_url` и `thumbnail_url` подписаны коротким токеном (по умолчанию 60 минут), поэтому
их можно сразу ставить в `<video src>` и `<img src>` — заголовок `Authorization` не
нужен, перемотка работает через HTTP Range:

```tsx
{answer.videos.map((video) => (
  <figure key={video.id}>
    <video
      controls
      preload="metadata"
      playsInline
      poster={video.thumbnail_url ? API_URL + video.thumbnail_url : undefined}
      src={API_URL + video.stream_url}
    />
    <figcaption>{video.title}</figcaption>
  </figure>
))}
```

Ссылки не продлеваются: если пользователь вернулся к старому ответу после `expires_at`,
плеер получит `401` — задайте вопрос заново или откройте ролик из списка видео
администратора. Архивированные и удалённые ролики перестают проигрываться сразу (`404`).

## 7. Отдельные speech-функции

Эти маршруты не выполняют RAG. Они нужны, если frontend хочет отдельно распознавать запись
или озвучивать готовый текст.

### Распознавание аудио

`POST /api/v1/speech/transcribe`, `multipart/form-data`:

- `file` — обязательно;
- `language` — необязательно: `kk`, `ru`, `en`.

```json
{
  "text": "Распознанный текст",
  "language": "ru",
  "duration_seconds": 4.27,
  "provider": "elevenlabs",
  "model": "scribe_v2"
}
```

Для форматов, отличных от WAV, `duration_seconds` может быть `null`.

### Озвучивание текста

`POST /api/v1/speech/synthesize`

```json
{
  "text": "Текст для озвучивания",
  "language": "ru",
  "voice_id": null,
  "speed": 1.0,
  "output_format": "mp3"
}
```

Ограничения: текст до 5000 символов, скорость `0.25..1.5`, формат `mp3` или `wav`.
Ответ — бинарный аудиофайл, не JSON. Фактические параметры находятся в заголовках:

- `X-Audio-Provider`;
- `X-Audio-Model`;
- `X-Voice-ID`;
- `X-AI-Generated-Voice: true`.

### Список голосов

`GET /api/v1/speech/voices`

```json
{
  "default_voice_id": "voice-id",
  "voices": [
    {
      "voice_id": "voice-id",
      "name": "Configured ElevenLabs voice",
      "provider": "elevenlabs",
      "languages": ["kk", "ru", "en"],
      "configured": true
    }
  ]
}
```

Показывать пользователю желательно только голоса с `configured: true`.

## 8. Документы: интерфейс `org_admin`

Документ становится доступен RAG только после успешной обработки и утверждения.

### Загрузка

`POST /api/v1/documents/upload`, `multipart/form-data`:

| Поле | Значение |
|---|---|
| `file` | PDF, DOCX, DOC (Word 97–2003), TXT или MD |
| `title` | 2–500 символов |
| `language` | `kk`, `ru` или `en` |
| `organization_id` | только для `super_admin` |

Максимальный размер по текущей конфигурации — 50 MB. TXT и MD должны быть в UTF-8.
Старые `.doc` при обработке автоматически конвертируются в DOCX (LibreOffice в worker);
для скачивания хранится исходный файл. Указывайте в `title` номер инструкции
(«Инструкция №90 — по ТБ при работе на высоте»): он показывается в источниках ответа и
используется при оценке качества поиска.

### Обработка и утверждение

После загрузки frontend должен опрашивать:

`GET /api/v1/documents/{document_id}/status`

примерно раз в 2–3 секунды, пока `latest_job.status` не станет `succeeded` или `failed`.

Основные статусы:

- `document.status`: `uploaded`, `processing`, `ready`, `failed`, `archived`;
- `document.approval_status`: `pending`, `approved`, `rejected`, `archived`;
- `latest_job.status`: `pending`, `running`, `succeeded`, `failed`, `cancelled`;
- `latest_job.progress`: число от 0 до 100;
- при сбое текст находится в `latest_job.error_message`.

После `latest_job.status === "succeeded"` администратор нажимает «Утвердить»:

`POST /api/v1/documents/{document_id}/approve`

После этого документ должен иметь `status: "ready"` и
`approval_status: "approved"` и участвует в ответах RAG.

### Остальные document-маршруты

- `GET /api/v1/documents` — список;
- `GET /api/v1/documents/{id}` — карточка;
- `GET /api/v1/documents/{id}/versions` — версии;
- `POST /api/v1/documents/{id}/versions` — новая версия (`file`, необязательный `language`);
- `GET /api/v1/documents/{id}/download` — защищённое скачивание;
- `POST /api/v1/documents/{id}/archive` — архивировать и исключить из RAG;
- `POST /api/v1/documents/{id}/reindex` — повторная индексация;
- `DELETE /api/v1/documents/{id}` — окончательное удаление, ответ `204`.

Скачивание также нужно делать через авторизованный `fetch` и `Blob URL`, как аудио.

### Обучающие видео

Ролики живут отдельно от документов, но проходят такой же путь: загрузка → обработка →
утверждение. Ассистент предлагает только утверждённые ролики своей организации.

**Загрузка** — `POST /api/v1/videos`, `multipart/form-data`:

| Поле | Обязательно | Описание |
|---|---|---|
| `file` | да | MP4, M4V, MOV или WEBM, до 500 MB и 30 минут |
| `title` | да | название карточки, 2–500 символов |
| `description` | нет | что показано в ролике; участвует в подборе |
| `example_questions` | нет | повторяйте поле для каждого вопроса, на который отвечает ролик |
| `linked_document_ids` | для утверждения | повторяйте поле для каждой инструкции, которую иллюстрирует ролик |
| `language` | нет | `kk`, `ru` (по умолчанию) или `en` |
| `organization_id` | только `super_admin` | организация |

```ts
const form = new FormData();
form.append("file", file);
form.append("title", "Проверка страховочной привязи и стропа");
form.append("description", "Осмотр швов, бирки; после рывка — вывести из эксплуатации");
["Как проверить страховочную привязь?", "Можно ли пользоваться поясом после рывка?"]
  .forEach((q) => form.append("example_questions", q));
form.append("linked_document_ids", instruction90Id);
const video = await api("/api/v1/videos", { method: "POST", body: form });
```

Ответ — `VideoRead` со `status: "processing"`. Воркер определяет длительность и размер
кадра, переносит индекс MP4 в начало файла (видео начинает играть до полной загрузки),
делает превью и считает векторы карточки. Опрашивайте `GET /api/v1/videos/{id}` раз в
2–3 секунды до `ready` или `failed` (`error_message` объясняет причину).

Статусы: `processing` → `ready` → `approved`; `archived`; `failed`.

**Утверждение** — `POST /api/v1/videos/{id}/approve`. Требует статус `ready` и хотя бы одну
привязанную инструкцию (иначе `422`). Проверьте ролик перед утверждением: `VideoRead`
для администратора содержит подписанные `stream_url` и `thumbnail_url` уже в статусе
`ready`.

**Редактирование** — `PATCH /api/v1/videos/{id}` с JSON (`title`, `description`,
`example_questions`, `linked_document_ids`, `language` — любые из них). Изменение текста
карточки сразу пересчитывает векторы. Утверждённый ролик нельзя отвязать от всех
инструкций.

Лучший способ улучшить подбор — добавлять в `example_questions` реальные формулировки
сотрудников, в том числе на казахском.

Если обработка завершилась `failed` из-за временного сбоя (хранилище, провайдер
эмбеддингов), покажите `error_message` и кнопку «Повторить» —
`POST /api/v1/videos/{id}/reprocess` запускает обработку заново без повторной загрузки
файла.

Остальные маршруты: `GET /api/v1/videos?status=approved` (список),
`POST /api/v1/videos/{id}/archive`, `DELETE /api/v1/videos/{id}` (удаляет и файл).

## 9. Управление пользователями

Доступ: `super_admin`, `org_admin`.

- `POST /api/v1/users`
- `GET /api/v1/users`
- `PATCH /api/v1/users/{user_id}`
- `DELETE /api/v1/users/{user_id}` — мягкая деактивация, ответ `204`.

Создание пользователя:

```json
{
  "organization_id": "uuid",
  "email": "employee@example.com",
  "password": "at-least-12-chars",
  "first_name": "Иван",
  "last_name": "Иванов",
  "role": "user"
}
```

Правила:

- пароль — от 12 до 256 символов;
- `org_admin` может создавать и менять только обычных `user` своей организации;
- `super_admin` может создавать все роли;
- у `super_admin` организация должна быть `null`;
- у `org_admin` и `user` организация обязательна;
- текущий пользователь не может отключить сам себя.

Обновление:

```json
{
  "first_name": "Новое имя",
  "last_name": "Новая фамилия",
  "is_active": true,
  "role": "user"
}
```

Все поля PATCH необязательные.

## 10. Управление организациями

Доступно только `super_admin`:

- `POST /api/v1/organizations`;
- `GET /api/v1/organizations`;
- `PATCH /api/v1/organizations/{organization_id}`.

Создание:

```json
{
  "name": "Название организации",
  "description": "Описание"
}
```

Отключение организации:

```json
{
  "is_active": false
}
```

После отключения все пользователи этой организации сразу теряют доступ, включая уже
выданные access и refresh tokens.

## 11. Поиск и низкоуровневый RAG

Обычно frontend использует `/chat/messages` или `/voice/ask`. Эти маршруты нужны для
административной диагностики и отдельного поискового интерфейса.

### Поиск по базе знаний

`POST /api/v1/knowledge-base/search`

```json
{
  "query": "пожарная безопасность",
  "limit": 10
}
```

`limit`: от 1 до 50.

`GET /api/v1/knowledge-base/stats` возвращает число активных утверждённых фрагментов:

```json
{
  "organization_id": "uuid",
  "active_chunks": 128
}
```

### RAG retrieval без генерации ответа

`POST /api/v1/rag/retrieve`

```json
{
  "query": "Что делать при пожаре?",
  "response_language": "ru"
}
```

Возвращает нормализованный вопрос, найденный контекст, источники, предупреждения и флаг
`insufficient_context`. Обычному пользовательскому экрану этот endpoint не нужен.

## 12. Обучение по ТБ и допуски к работам

> Статус внедрения: маршруты реализованы и проверены локально. До применения миграции и
> обновления backend на сервере они не появятся в production Swagger.

### 12.1. Текущая логика MVP

Для каждого demo-сотрудника назначено пять этапов:

1. `introductory` — вводный инструктаж;
2. `profession` — безопасность по профессии;
3. `ppe_first_aid` — СИЗ и первая помощь;
4. `special_hazards` — специальный опасный вид работ;
5. `final_assessment` — итоговая проверка.

Пока сотрудник не проходит вопросы через frontend. Результат вручную фиксирует
`org_admin` или `super_admin`. Обычный `user` может только просматривать собственные
результаты. Вход в приложение не блокируется при несданной ТБ: блокируется только
соответствующий производственный допуск.

| Операция | `user` | `org_admin` | `super_admin` |
|---|:---:|:---:|:---:|
| Посмотреть собственную ТБ | да | да | да |
| Посмотреть сотрудника своей организации | только себя | да | да |
| Получить список сотрудников | нет | своя организация | все организации |
| Изменить результат этапа | нет | своя организация | любая организация |

### 12.2. Типы frontend

```ts
type StoredSafetyStageStatus =
  | "not_started"
  | "in_progress"
  | "passed"
  | "failed";

// expired вычисляет backend. Отправлять его в PATCH нельзя.
type SafetyStageStatus = StoredSafetyStageStatus | "expired";
type OverallSafetyStatus = "allowed" | "partial" | "blocked";
type WorkScopeStatus = "allowed" | "blocked";

type SafetyStage = {
  id: string;
  order: number;
  code: string;
  title: string;
  status: SafetyStageStatus;
  score: number | null;
  passing_score: number;
  activity_code: string | null;
  passed_at: string | null;
  expires_at: string | null;
  notes: string | null;
};

type WorkScope = {
  code: string;
  title: string;
  status: WorkScopeStatus;
  blocking_stage_codes: string[];
};

type EmployeeSafety = {
  user_id: string;
  organization_id: string;
  email: string;
  first_name: string;
  last_name: string;
  personnel_number: string;
  position_code: string;
  position_title: string;
  hire_year: number;
  completed_stages: number;
  total_stages: number;
  progress_percent: number;
  overall_status: OverallSafetyStatus;
  has_any_work_access: boolean;
  stages: SafetyStage[];
  work_scopes: WorkScope[];
};
```

### 12.3. Получить собственный статус

`GET /api/v1/safety/employees/me`

Доступ: любой авторизованный пользователь с созданным safety-профилем.

```ts
async function getMySafety(accessToken: string): Promise<EmployeeSafety> {
  const response = await fetch(`${API_URL}/api/v1/safety/employees/me`, {
    headers: { Authorization: `Bearer ${accessToken}` },
  });
  if (!response.ok) throw await apiError(response);
  return response.json();
}
```

Пример ответа для электрика:

```json
{
  "user_id": "2165cf25-7e8e-4bd0-bddc-c26cc9a63258",
  "organization_id": "bb0c8469-ac67-46c2-9858-5ab7d9acd709",
  "email": "bagzhan.tolepbergen@semyzbay.kz",
  "first_name": "Багжан",
  "last_name": "Толепберген",
  "personnel_number": "DEMO-EL-001",
  "position_code": "electrician",
  "position_title": "Электрик",
  "hire_year": 2025,
  "completed_stages": 4,
  "total_stages": 5,
  "progress_percent": 80,
  "overall_status": "partial",
  "has_any_work_access": true,
  "stages": [
    {
      "id": "bd8eb539-86ba-4633-ac2f-783cb474661c",
      "order": 4,
      "code": "special_hazards",
      "title": "Безопасность работ на высоте",
      "status": "failed",
      "score": 65,
      "passing_score": 80,
      "activity_code": "work_at_height",
      "passed_at": null,
      "expires_at": null,
      "notes": "Работа на высоте запрещена до успешной пересдачи"
    }
  ],
  "work_scopes": [
    {
      "code": "electrical_work",
      "title": "Электромонтажные работы",
      "status": "allowed",
      "blocking_stage_codes": []
    },
    {
      "code": "work_at_height",
      "title": "Работы на высоте",
      "status": "blocked",
      "blocking_stage_codes": ["special_hazards"]
    }
  ]
}
```

В реальном ответе массив `stages` содержит все пять этапов. В примере оставлен один этап
для краткости.

### 12.4. Получить список сотрудников

`GET /api/v1/safety/employees`

Доступ: только `org_admin` и `super_admin`. Ответ: `EmployeeSafety[]`.

- `org_admin` автоматически получает только свою организацию;
- `super_admin` получает все организации;
- query-параметр `organization_id` этому маршруту сейчас не передаётся.

```ts
async function listEmployeeSafety(accessToken: string): Promise<EmployeeSafety[]> {
  const response = await fetch(`${API_URL}/api/v1/safety/employees`, {
    headers: { Authorization: `Bearer ${accessToken}` },
  });
  if (!response.ok) throw await apiError(response);
  return response.json();
}
```

### 12.5. Получить конкретного сотрудника

`GET /api/v1/safety/employees/{user_id}`

- сотрудник может запросить только собственный `user_id`;
- `org_admin` может запросить сотрудника своей организации;
- `super_admin` может запросить любого сотрудника.

Отсутствие safety-профиля возвращает `404 Employee safety profile not found`.

### 12.6. Изменить результат вручную

`PATCH /api/v1/safety/employees/{user_id}/stages/{stage_code}`

Доступ: только `org_admin` и `super_admin`. В ответ backend возвращает целиком обновлённый
`EmployeeSafety`, поэтому frontend может сразу заменить объект в кеше.

```ts
type SafetyStageUpdate = {
  status: StoredSafetyStageStatus;
  score?: number | null;
  expires_at?: string | null;
  notes?: string | null;
};

async function updateSafetyStage(
  accessToken: string,
  userId: string,
  stageCode: string,
  update: SafetyStageUpdate,
): Promise<EmployeeSafety> {
  const response = await fetch(
    `${API_URL}/api/v1/safety/employees/${userId}/stages/${stageCode}`,
    {
      method: "PATCH",
      headers: {
        Authorization: `Bearer ${accessToken}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify(update),
    },
  );
  if (!response.ok) throw await apiError(response);
  return response.json();
}
```

Успешное прохождение:

```json
{
  "status": "passed",
  "score": 88,
  "expires_at": "2027-11-10T23:59:59+05:00",
  "notes": "Повторная проверка знаний"
}
```

Неуспешный результат:

```json
{
  "status": "failed",
  "score": 65,
  "expires_at": null,
  "notes": "Назначить повторную проверку"
}
```

Правила валидации:

- `score` находится в диапазоне от `0` до `100`;
- для `passed` поле `score` обязательно;
- для `passed` балл должен быть не ниже `passing_score`, иначе возвращается `422`;
- `expires_at` для `passed` должен быть в будущем и обязательно содержать timezone;
- `notes` — не более 2000 символов;
- `expired` является только вычисляемым ответным статусом и не принимается в PATCH;
- при переводе из `passed` в другой статус backend очищает `passed_at`.

### 12.7. Как frontend проверяет допуск

Отдельного маршрута `/check-access` сейчас нет. Источником истины является
`work_scopes` из любого ответа `EmployeeSafety`.

```ts
function canPerform(employee: EmployeeSafety, activityCode: string): boolean {
  return employee.work_scopes.some(
    (scope) => scope.code === activityCode && scope.status === "allowed",
  );
}
```

Не следует использовать только `has_any_work_access`: оно означает, что сотруднику разрешён
хотя бы один вид работ. Для конкретного задания всегда нужно проверять соответствующий
`work_scopes[].code`.

Расчёт backend:

- непройденный общий этап с `activity_code = null` блокирует все виды работ сотрудника;
- непройденный специальный этап блокирует только совпадающий `activity_code`;
- истёкший `passed` возвращается как `expired` и считается непройденным;
- `allowed` означает, что разрешены все назначенные виды работ;
- `partial` означает, что разрешена только часть работ;
- `blocked` означает, что не разрешён ни один назначенный вид работ.

### 12.8. Рекомендации по интерфейсу

Экран сотрудника:

- прогресс `completed_stages / total_stages` и `progress_percent`;
- список пяти этапов с баллом и сроком действия;
- отдельные зелёные/красные карточки для каждого `work_scope`;
- расшифровка блокировки через `blocking_stage_codes` и соответствующие `stages`;
- несданная ТБ не должна автоматически разлогинивать пользователя.

Экран администратора:

- таблица сотрудников: ФИО, должность, прогресс, `overall_status`;
- фильтр на frontend по `allowed`, `partial`, `blocked`;
- карточка сотрудника с пятью этапами;
- ручная форма изменения статуса, балла, срока и комментария;
- подтверждение перед изменением `passed` на `failed` или `not_started`.

### 12.9. Demo-аккаунты

Логины уникальны, чтобы результаты сотрудников не смешивались. Пароль для локальной
демонстрации одинаковый:

| Сотрудник | Должность | Логин | Ожидаемый статус |
|---|---|---|---|
| Багжан Толепберген | Электрик | `bagzhan.tolepbergen@semyzbay.kz` | `partial`, 4/5; высота заблокирована |
| Абай Кождан | Сварщик | `abai.kozhdan@semyzbay.kz` | `allowed`, 5/5 |
| Нуртас Бакбергенов | Водитель | `nurtas.bakbergenov@semyzbay.kz` | `blocked`, 0/5 |

Общий локальный пароль: `DanaAI-Demo-2026!`. Эти учётные данные предназначены только для
демонстрации и не должны использоваться для реальных сотрудников или production.

## 13. Ошибки

Обычная ошибка FastAPI:

```json
{
  "detail": "Document not found"
}
```

Ошибка валидации может содержать массив в `detail`:

```json
{
  "detail": [
    {
      "type": "string_too_short",
      "loc": ["body", "query"],
      "msg": "String should have at least 2 characters",
      "input": "a"
    }
  ]
}
```

Основные HTTP-коды:

| Код | Значение для UI |
|---:|---|
| `400` | Неверная операция |
| `401` | Сессия истекла, попробовать refresh |
| `403` | Нет прав или попытка доступа к другой организации |
| `404` | Объект не найден |
| `409` | Конфликт состояния или дубликат |
| `413` | Файл слишком большой |
| `415` | Формат файла не поддерживается |
| `422` | Ошибка данных формы/JSON |
| `502` | Ошибка внешнего AI/audio-провайдера или storage |
| `503` | Зависимость backend временно недоступна |

Универсальный parser:

```ts
async function apiError(response: Response): Promise<Error> {
  const requestId = response.headers.get("X-Request-ID");
  let message = `HTTP ${response.status}`;

  try {
    const body = await response.json();
    if (typeof body.detail === "string") {
      message = body.detail;
    } else if (Array.isArray(body.detail)) {
      message = body.detail.map((item: { msg?: string }) => item.msg).filter(Boolean).join(", ");
    }
  } catch {
    // Ответ мог быть бинарным или пустым.
  }

  return new Error(requestId ? `${message} (request: ${requestId})` : message);
}
```

## 14. Минимальный набор экранов frontend

Для MVP достаточно:

1. Вход.
2. Главный экран голосового агента: запись → ожидание → transcript → ответ → MP3 → источники.
3. Текстовый вопрос как запасной способ ввода.
4. Для `org_admin`: список документов, загрузка, прогресс обработки, утверждение, архив.
5. Для `org_admin`: список пользователей, создание, включение/отключение.
6. Для `super_admin`: организации и пользователи.
7. Для сотрудника: пять этапов ТБ и отдельные статусы допуска к видам работ.

Историю чатов можно пока не реализовывать. Backend создаёт технические conversation/message
записи автоматически, поэтому голосовой и текстовый сценарии работают без отдельного экрана
истории.

## 15. Полный список маршрутов

Публичные:

- `GET /health`
- `GET /health/ready`
- `POST /api/v1/auth/login`
- `POST /api/v1/auth/refresh`
- `POST /api/v1/auth/logout`

С access token:

- `GET /api/v1/auth/me`
- `POST /api/v1/chat/messages`
- `POST /api/v1/chat/messages/stream`
- `POST /api/v1/voice/ask`
- `GET /api/v1/voice/messages/{message_id}/audio`
- `POST /api/v1/speech/transcribe`
- `POST /api/v1/speech/synthesize`
- `GET /api/v1/speech/voices`
- `POST /api/v1/conversations`
- `GET /api/v1/conversations`
- `GET /api/v1/conversations/{conversation_id}/messages`
- `POST /api/v1/knowledge-base/search`
- `GET /api/v1/knowledge-base/stats`
- `POST /api/v1/rag/retrieve`
- `GET /api/v1/safety/employees/me`
- `GET /api/v1/safety/employees/{user_id}` (собственный профиль или администратор)
- `GET /api/v1/videos/{video_id}/stream` и `/thumbnail` (утверждённые ролики; вместо
  access token можно передать подписанный `?token=` из `stream_url`)

Только `org_admin`/`super_admin`:

- `POST /api/v1/documents/upload`
- `GET /api/v1/documents`
- `GET /api/v1/documents/{document_id}`
- `GET /api/v1/documents/{document_id}/versions`
- `POST /api/v1/documents/{document_id}/versions`
- `GET /api/v1/documents/{document_id}/status`
- `GET /api/v1/documents/{document_id}/download`
- `POST /api/v1/documents/{document_id}/approve`
- `POST /api/v1/documents/{document_id}/archive`
- `POST /api/v1/documents/{document_id}/reindex`
- `DELETE /api/v1/documents/{document_id}`
- `POST /api/v1/users`
- `GET /api/v1/users`
- `PATCH /api/v1/users/{user_id}`
- `DELETE /api/v1/users/{user_id}`
- `GET /api/v1/safety/employees`
- `PATCH /api/v1/safety/employees/{user_id}/stages/{stage_code}`
- `POST /api/v1/videos`
- `GET /api/v1/videos`
- `GET /api/v1/videos/{video_id}`
- `PATCH /api/v1/videos/{video_id}`
- `POST /api/v1/videos/{video_id}/approve`
- `POST /api/v1/videos/{video_id}/reprocess`
- `POST /api/v1/videos/{video_id}/archive`
- `DELETE /api/v1/videos/{video_id}`

Только `super_admin`:

- `POST /api/v1/organizations`
- `GET /api/v1/organizations`
- `PATCH /api/v1/organizations/{organization_id}`

