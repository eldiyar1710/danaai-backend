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
| `conversation_id` | нет | ID предыдущего диалога; можно не передавать |
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

Историю диалогов backend поддерживает, но для первой версии frontend её можно не выводить.
Если `conversation_id` не передать, backend автоматически создаст новый диалог.

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

`POST /api/v1/chat/messages/stream` возвращает Server-Sent Events:

- `metadata`;
- `text_delta`;
- `completed`.

Это POST, поэтому стандартный браузерный `EventSource` не подходит — нужен streaming
`fetch`. Текущая реализация сначала полностью проверяет RAG-ответ и только затем отдаёт его
частями. Для первой версии проще использовать обычный `/chat/messages`.

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
};
```

Рекомендуемое отображение:

- в тексте ответа оставить маркеры `[S1]`, `[S2]`;
- сделать маркер кликабельным;
- по клику открыть карточку источника с `text`, `page_number`, `section_title`;
- для администратора можно добавить переход к документу по `document_id`.

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
| `file` | PDF, DOCX, TXT или MD |
| `title` | 2–500 символов |
| `language` | `kk`, `ru` или `en` |
| `organization_id` | только для `super_admin` |

Максимальный размер по текущей конфигурации — 50 MB. TXT и MD должны быть в UTF-8.

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

## 12. Ошибки

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

## 13. Минимальный набор экранов frontend

Для MVP достаточно:

1. Вход.
2. Главный экран голосового агента: запись → ожидание → transcript → ответ → MP3 → источники.
3. Текстовый вопрос как запасной способ ввода.
4. Для `org_admin`: список документов, загрузка, прогресс обработки, утверждение, архив.
5. Для `org_admin`: список пользователей, создание, включение/отключение.
6. Для `super_admin`: организации и пользователи.

Историю чатов можно пока не реализовывать. Backend создаёт технические conversation/message
записи автоматически, поэтому голосовой и текстовый сценарии работают без отдельного экрана
истории.

## 14. Полный список маршрутов

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

Только `super_admin`:

- `POST /api/v1/organizations`
- `GET /api/v1/organizations`
- `PATCH /api/v1/organizations/{organization_id}`

