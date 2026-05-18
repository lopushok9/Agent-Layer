# План интеграции x402 для buyer-side

## Цель

Добавить поддержку x402 на стороне покупателя в существующий стек OpenClaw
wallet без появления второго кошелька. Агент должен уметь находить x402-paid
сервисы, делать preview стоимости, получать явное подтверждение, подписывать
платеж текущим OpenClaw-кошельком, выполнять paid request и возвращать ответ
провайдера.

Основные цели:

- buyer-flow для Base EVM
- buyer-flow для Solana
- discovery и paid calls для Agentic Market
- общий discovery через CDP Bazaar

Что не входит в v1:

- работа как x402 seller
- запуск собственного settlement facilitator
- поддержка всех EVM payment schemes в первой версии
- обход существующей модели безопасности `preview -> prepare -> execute`

## Что x402 меняет в нашей архитектуре

Сейчас у нас есть два отдельных мира:

- `agent-wallet/` отвечает за локальную подпись, approvals, spend policy и
  user intent
- `.openclaw/extensions/pay-bridge/` вызывает отдельный `pay.sh` wallet для
  paid API

Для buyer-side поддержки x402 нам не нужно расширять `pay-bridge`. Логику paid
requests нужно переносить в `agent-wallet`, чтобы:

- за сервисы платил тот же OpenClaw wallet identity
- paid calls были защищены той же approval token моделью
- те же per-user wallet bindings работали для Base и Solana
- пользователю не нужно было ставить второй кошелек и управлять вторым балансом

## Внешние свойства протокола, которые определяют дизайн

По текущей документации Coinbase/x402:

- buyer-flow в x402 HTTP-нативный: request -> `402 Payment Required` ->
  `PAYMENT-REQUIRED` header -> подпись payment payload -> повторный запрос с
  `PAYMENT-SIGNATURE` -> получение `PAYMENT-RESPONSE`
- CDP facilitator рекомендуется для Base и Solana; Solana поддерживает `exact`,
  а Base поддерживает `exact` и `upto`
- EVM exact payments обычно используют EIP-3009 для USDC/EURC и Permit2 для
  generic ERC-20
- Solana exact использует transaction-shaped payload, который facilitator
  валидирует и потом settlement-ит
- Bazaar discovery публичный и read-only; для него не нужны API keys

Это означает, что buyer-интеграция состоит из двух отдельных обязанностей:

1. Discovery и HTTP orchestration
2. Создание payment payload из наших локальных кошельков

Чтобы покупать у сторонних сервисов, нам не нужно поднимать свой facilitator.
Seller-side сервер и facilitator сами делают verification и settlement. Наш
wallet должен только корректно собирать buyer-side payload и применять локальную
policy до его создания.

## Дизайн верхнего уровня

### Новый capability slice

Добавить отдельный x402 buyer slice внутри `agent-wallet`:

- `agent_wallet/x402/` или `agent_wallet/providers/x402_*.py`
- разбор request/response
- discovery clients
- network-specific signer adapters
- approval-bound request execution
- receipt normalization

### Подпись остается локальной

Все payment signatures должны создаваться текущим OpenClaw wallet backend:

- Base: через существующий `wdk_evm_local`
- Solana: через существующий локальный Solana signer

Отдельный x402 private key хранить не нужно.

### Секреты держим на сервере только там, где это действительно нужно

`provider-gateway/` может хранить remote integration secrets, если они нужны
для удобства или production-hardening, например:

- optional marketplace/provider credentials, которые не должны лежать в user env
- allowlisted discovery и relay configuration

Для buyer-side x402 flow это не требуется по умолчанию. Buyer-кошелек не
должен напрямую вызывать facilitator: он только строит и подписывает payment
payload, а seller-side сервер сам делает `verify/settle` локально или через
facilitator.

Но `provider-gateway` должен оставаться non-custodial:

- никаких user private keys
- никакой user signing
- никакого создания payment authorization
- никакой подмены локального approval flow

## Рекомендуемый rollout

### Phase 1: Base exact + Solana exact

Поставить базовый buyer-flow для fixed-price сервисов:

- fetch endpoint
- parse `PAYMENT-REQUIRED`
- выбор supported requirement
- preview цены, сети, asset, destination и request fingerprint
- обязательный host approval
- локальная подпись x402 payload
- retry запроса с `PAYMENT-SIGNATURE`
- parse `PAYMENT-RESPONSE`

Этого достаточно для большинства pay-per-request сервисов в стиле Agentic
Market.

### Phase 2: Discovery

Добавить:

- Agentic Market search/list helpers
- CDP Bazaar search/list helpers
- price/network filtering и preference policies

### Phase 3: Base `upto`

Добавить usage-based EVM billing после стабилизации exact flow. Это полезно, но
не требуется для первого релиза и недоступно на Solana.

### Phase 4: Permit2 и sponsored approval paths

Добавить поддержку:

- non-USDC ERC-20 payments через Permit2
- gas-sponsored approval paths, если сервер их рекламирует

Это должен быть второй EVM milestone, а не часть первого среза.

## Основные сущности, которые нужно добавить

### 1. `X402DiscoveryClient`

Ответственность:

- искать сервисы в Agentic Market
- искать сервисы в CDP Bazaar
- нормализовать ответ в одну внутреннюю модель

Желательные поля на выходе:

- service name
- provider / marketplace
- resource URL
- supported networks
- asset
- scheme
- price
- method
- request schema hints

### 2. `X402PaymentRequirement`

Каноническая внутренняя модель для распарсенного `PAYMENT-REQUIRED`.

Поля:

- `scheme`
- `network`
- `asset`
- `amount`
- `pay_to`
- `max_timeout_seconds`
- `resource_url`
- `http_method`
- `transfer_method`
- `raw_requirement`

Эта модель является мостом между discovery, preview, policy и execution.

### 3. `X402RequestPreview`

Это объект, который нужно привязывать к `approval_token`.

В нем должны быть:

- точный request URL
- method
- normalized query/body hash
- выбранный requirement
- network
- asset
- amount
- payee
- marketplace/source
- preview digest
- optional human summary

Это самый важный объект с точки зрения безопасности. Если итоговый paid request
в чем-то существенно отличается от preview, execute должен падать.

### 4. `X402BuyerClient`

Высокоуровневый orchestrator paid request flow.

Ответственность:

- выполнить unpaid request
- определить `402`
- декодировать `PAYMENT-REQUIRED`
- выбрать лучший совместимый requirement на основе локальных policies
- создать preview
- создать payment payload через правильный signer adapter
- повторить request с `PAYMENT-SIGNATURE`
- вернуть нормализованный response и payment receipt

### 5. `X402SignerAdapter`

Network-specific signer boundary, которым пользуется `X402BuyerClient`.

Реализации:

- `X402EvmSignerAdapter`
- `X402SolanaSignerAdapter`

Это позволяет не размазывать зависимость от x402 SDK по остальному wallet
backend.

### 6. `X402Policy`

Локальные policy checks перед созданием платежа:

- allowed networks
- max per-call spend
- allowed assets
- marketplace allowlist / denylist
- method allowlist
- optional provider/domain allowlist

Эта часть должна переиспользовать дух существующих `transaction_policy.py` и
`spending_limits.py`, но работать не только с chain transfers, а с paid HTTP
requests.

### 7. `X402Receipt`

Нормализованное представление `PAYMENT-RESPONSE`.

Поля:

- `success`
- `network`
- `payer`
- `transaction`
- `amount`
- `settled_at`
- `provider_response_status`
- `provider_response_headers`

Нужно хранить достаточно данных для аудита и отладки.

## Модель Facilitator в нашем дизайне

### Что делает facilitator

В x402 facilitator валидирует payment payload и settlement-ит его onchain от
лица seller-side. Также он часто спонсирует gas / fees для поддерживаемых сетей
и методов.

### Чего facilitator не делает за нас

Для buyer-support facilitator не является ни нашим wallet, ни нашим signer, ни
нашей policy engine.

Его нужно трактовать так:

- как внешнюю инфраструктуру, с которой мы должны быть совместимы
- не как место, куда нужно переносить buyer custody
- не как повод хранить user keys вне локального wallet

### Где здесь место `provider-gateway`

`provider-gateway` не должен становиться facilitator. Он должен быть максимум
optional control plane вокруг facilitator usage:

- хранить CDP API credentials, если они нужны для authenticated facilitator
  endpoints
- давать allowlisted discovery/search helpers
- предоставлять marketplace metadata helpers
- централизовать rate limiting, retries и logging для удаленных discovery
  сервисов
- опционально проксировать facilitator discovery calls, если мы захотим
  стабильное response shaping

Он не должен:

- подписывать x402 buyer payloads
- хранить user wallet material
- отправлять buyer-authorized payments за пользователя вне x402

## Chain-specific детали реализации

### Base / EVM

#### Рекомендуемый scope для v1

Начать с `exact` на Base через USDC.

Причины:

- это самый чистый buyer UX
- это соответствует основному use case Agentic Market
- это позволяет не тащить лишнюю сложность Permit2 в первый milestone

#### Главный integration gap в нашем коде

`wdk_evm_local` сейчас умеет transfer и protocol actions, но не дает generic
typed-data signing surface, нужный для x402 EIP-3009 / Permit2 payloads.

Поэтому Base support требует одного из двух путей:

1. Расширить `wdk-evm-wallet` узким x402 signing endpoint
2. Пересобрать EVM signing прямо в Python из локально доступного key source

Для этого репозитория правильный путь - первый, потому что `wdk-evm-wallet`
уже является EVM authority и user binding layer.

#### Что нужно добавить для EVM

В `wdk-evm-wallet/`:

- localhost-only endpoint для подписи x402-specific EIP-712 payloads
- сделать его узким: только x402 exact / permit2 shapes, без arbitrary typed
  data
- возвращать address, chain id, domain hash и signature metadata

В `agent-wallet/`:

- добавить `X402EvmSignerAdapter`, который вызывает локальный WDK service
- маппить Base в CAIP-2 `eip155:8453`
- позже добавить Base Sepolia как `eip155:84532` для тестов

#### Approval semantics

Создание EVM x402 payment все равно должно идти через:

- preview: quote платежа и request fingerprint
- execute: создание payload и отправка request

Нельзя добавлять свободный "sign arbitrary x402 payment" tool.

### Solana

#### Рекомендуемый scope для v1

Поддержать `exact` на Solana mainnet и devnet.

#### Почему Solana отличается

Solana exact не является EIP-3009-style authorization. Там payload
transaction-oriented, и официальные facilitator validation rules накладывают
жесткие ограничения на transfer instruction shape, ATA correctness, simulation
и fee payer handling.

Это значит, что Solana implementation нельзя внутренне переиспользовать из
Base flow, хотя для пользователя UX должен выглядеть одинаково.

#### Что нужно добавить для Solana

В `agent-wallet/`:

- построить `X402SolanaSignerAdapter` поверх существующего локального Solana
  signer
- убедиться, что network mapping использует CAIP-2 Solana identifiers
- по возможности поддержать SPL Token Program и Token2022
- по возможности делать локальную simulation перед execute, чтобы падать с
  понятной wallet-side ошибкой, а не с opaque facilitator error

Этот путь заметно проще, чем EVM, потому что Solana signer у нас уже живет в
Python.

## Tool surface, который нужно добавить

Поверхность должна быть узкой и безопасной.

Рекомендуемые tools:

- `x402_search_services`
- `x402_get_service_details`
- `x402_preview_request`
- `x402_execute_request`
- `x402_get_payment_receipt`

Опциональные Agentic Market convenience tools:

- `x402_search_agentic_market`
- `x402_list_agentic_market_categories`

Чего не надо добавлять:

- arbitrary raw x402 signing tools
- arbitrary facilitator verify/settle tools
- tools, которые принимают неограниченные shell commands или opaque external
  request blobs

## Форма preview / execute

### Preview

`x402_preview_request` должен:

- при необходимости сначала discover-ить resource
- выполнить unpaid request
- распарсить `402`
- выбрать preferred compatible payment option
- проверить local spend policy
- вернуть confirmation summary

В confirmation summary должны быть:

- URL + method
- provider / marketplace
- network
- asset
- amount
- `payTo`
- scheme
- transfer method, если он есть
- request body hash для POST requests

### Execute

`x402_execute_request` должен:

- требовать `approval_token`
- заново проверить request fingerprint
- создавать payment payload только после успешной проверки approval
- повторять HTTP request с `PAYMENT-SIGNATURE`
- парсить и возвращать `PAYMENT-RESPONSE`
- записывать spend для limit enforcement

## Workstream для `provider-gateway`

### Какие endpoints можно рассмотреть

Read-only / relay endpoints:

- `GET /v1/x402/discovery/search`
- `GET /v1/x402/discovery/resources`
- `GET /v1/x402/agentic-market/search`
- `GET /v1/x402/agentic-market/services`

Optional helper endpoints:

- `GET /v1/x402/policies`

Я бы избегал generic `POST /v1/x402/pay` в v1, потому что он слишком легко
размывает границу wallet-side signing и request execution.

### Модель секретов

Env-backed secrets добавлять только если реально нужно:

- optional marketplace API credentials
- internal allowlist / routing config

User-specific spend policy и approval data должны оставаться локальными в
`agent-wallet`.

## Конкретные file-level workstreams

### `agent-wallet/`

Добавить:

- `agent_wallet/providers/x402_discovery.py`
- `agent_wallet/providers/x402_http.py`
- `agent_wallet/providers/x402_agentic_market.py`
- `agent_wallet/x402_signers/evm.py`
- `agent_wallet/x402_signers/solana.py`

Обновить:

- [`agent_wallet/openclaw_adapter.py`](./agent_wallet/openclaw_adapter.py)
- [`agent_wallet/plugin_bundle.py`](./agent_wallet/plugin_bundle.py)
- [`agent_wallet/openclaw_runtime.py`](./agent_wallet/openclaw_runtime.py)
- [`agent_wallet/config.py`](./agent_wallet/config.py)
- [`agent_wallet/spending_limits.py`](./agent_wallet/spending_limits.py)
- [`agent_wallet/transaction_policy.py`](./agent_wallet/transaction_policy.py)
- [`agent_wallet/openclaw_cli.py`](./agent_wallet/openclaw_cli.py)

### `wdk-evm-wallet/`

Добавить:

- narrow x402 signing endpoint(s)
- валидацию supported x402 EIP-712 payload shapes
- smoke tests на Base mainnet / Base Sepolia signing compatibility

### `.openclaw/extensions/agent-wallet/`

Обновить:

- tool registration
- tool descriptions
- approval-preview caching для x402 request previews
- config schema для x402 feature flags / preferences

### `provider-gateway/`

Добавить:

- read-only x402 discovery relays
- optional facilitator capability relay
- response normalization и allowlisting

## Рекомендуемые configuration fields

В `agent_wallet/config.py` и OpenClaw plugin config:

- `x402_enabled`
- `x402_preferred_networks`
- `x402_preferred_assets`
- `x402_allow_domains`
- `x402_deny_domains`
- `x402_max_payment_usdc`
- `x402_discovery_provider`
- `x402_agentic_market_base_url`

Только facilitator или marketplace credentials, которые действительно должны
оставаться секретными, должны жить в `provider-gateway` env, а не в локальном
plugin config.

## Spend policy и user safety

Эта интеграция должна сохранить текущую safety posture кошелька.

Обязательные safeguards:

- никакого auto-pay без execute approval
- привязка approval к request fingerprint + payment requirement
- поддержка domain allowlist
- per-call spend cap
- daily x402 spend cap
- network allowlist
- явная индикация, когда request тратит реальные mainnet funds

Nice-to-have safeguards:

- per-provider spend caps
- режим "только Agentic Market"
- deny POST by default для неизвестных доменов

## Observability и audit

Нужны structured logs для:

- previewed requests
- rejected previews
- payment creation failures
- execute success/failure
- receipt metadata

Чего нельзя логировать:

- raw secrets
- полные sensitive request bodies без необходимости
- raw signed payloads, если только они специально не редактируются

## План тестирования

### Unit / smoke

`agent-wallet/tests/`:

- parse `PAYMENT-REQUIRED`
- build preview summaries
- approval token binding на x402 request previews
- Base exact payload creation
- Solana exact payload creation
- execute retry behavior
- receipt parsing
- spend-limit enforcement

`provider-gateway/`:

- discovery relay auth
- upstream error shaping
- allowlist enforcement

`wdk-evm-wallet/`:

- x402 typed-data signing
- Base chain mismatch rejection
- unsupported payload rejection

### Live

Начать с:

- Base Sepolia + x402.org test facilitator
- Solana Devnet + x402.org test facilitator

Потом перейти к:

- Base mainnet + сервисы, совместимые с CDP facilitator
- Solana mainnet + сервисы, совместимые с CDP facilitator

## Рекомендуемый порядок реализации

1. Добавить read-only discovery clients и preview models в `agent-wallet`
2. Добавить Solana exact signing path в Python
3. Добавить Base exact x402 signing path в `wdk-evm-wallet` + Python adapter
4. Добавить OpenClaw tools для preview/execute
5. Добавить `provider-gateway` discovery relays и secret-backed config
6. Добавить live test coverage на testnets
7. Добавить Agentic Market convenience search
8. Добавить Permit2, а затем `upto` на Base

## Рекомендация

Правильный первый релиз выглядит так:

- интегрировать x402 в `agent-wallet`, а не в `pay-bridge`
- поддержать сначала `exact`
- выпустить вместе Solana exact и Base exact
- оставить discovery read-only в `provider-gateway`
- добавить EVM x402 signing в `wdk-evm-wallet`, а не вытаскивать private keys в
  x402 SDK

Это самый короткий путь к модели "платим из нашего кошелька" без разрушения
текущей non-custodial и approval-first архитектуры репозитория.
