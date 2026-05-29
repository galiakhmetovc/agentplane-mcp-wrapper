# AgentPlane MCP Wrapper

Локальный адаптер для подключения Codex, Claude и IDE-агентов к демо
AgentPlane.

В этом репозитории только клиентский адаптер. Политики, серверный шлюз,
точки исполнения, вход пользователей, аудит и веб-консоль работают на стороне
AgentPlane.

## Быстрый старт

```bash
git clone https://github.com/galiakhmetovc/agentplane-mcp-wrapper.git
cd agentplane-mcp-wrapper
uv sync
uv run agentplane-mcp-wrapper status --config examples/agentplane.tech.toml
```

Если токена нет, это нормально: первый вызов из агента вернет ссылку входа
AgentPlane и одноразовый код.

## Подключение к Codex / Claude

Укажите локальный MCP server:

```bash
uv run --project /path/to/agentplane-mcp-wrapper \
  agentplane-mcp-wrapper serve \
  --config /path/to/agentplane-mcp-wrapper/examples/agentplane.tech.toml
```

После подключения попросите агента:

```text
Покажи доступные MCP tools через agent-control-plane
```

Если локальная сессия отсутствует, wrapper вернет ссылку входа AgentPlane
и одноразовый код прямо в ответе агента. Откройте ссылку, подтвердите код и
повторите тот же запрос агенту.

Пароль не передается wrapper-у или агенту.

## Что делает wrapper

- запускается как stdio MCP server на рабочей машине пользователя;
- получает пользовательскую сессию через безопасный browser/device-code вход;
- хранит short-lived token cache вне репозитория;
- проксирует MCP-запросы в `https://mcp.agentplane.tech/mcp`;
- не принимает решений безопасности и не исполняет tools локально.

## Доступные локальные команды

```bash
uv run agentplane-mcp-wrapper login --config examples/agentplane.tech.toml
uv run agentplane-mcp-wrapper status --config examples/agentplane.tech.toml
uv run agentplane-mcp-wrapper logout --config examples/agentplane.tech.toml
uv run agentplane-mcp-wrapper serve --config examples/agentplane.tech.toml
```

## Конфигурация

Основной файл демо:

```text
examples/agentplane.tech.toml
```

Токены по умолчанию лежат в:

```text
~/.agentplane/mcp-wrapper-token.json
```

Этот файл не нужно коммитить и передавать другим пользователям.
