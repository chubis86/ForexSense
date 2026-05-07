# ForexSense

Agente Python que monitorea BTC/USDT, ETH/USDT, XAU/USD y EUR/USD cada hora y envía señales de trading a Telegram combinando análisis técnico clásico con Claude AI.

## Cómo funciona

```
Datos 1H + 4H → Filtro diario ±2% → TA (RSI/MACD/Bollinger) → Patrones chartistas → Claude → Telegram
```

Señales solo se envían si Claude confirma strength **HIGH** o **MEDIUM**. El bot es informativo — tú decides si operar.

## Setup en 5 pasos

### 1. Crear bot de Telegram

1. Abre Telegram y busca `@BotFather`
2. Envía `/newbot` y sigue las instrucciones
3. Guarda el **token** que te da BotFather (formato: `123456:ABCdef...`)
4. Para obtener tu **chat_id**: busca `@userinfobot` en Telegram y envíale cualquier mensaje — te responde con tu ID

### 2. Hacer fork del repositorio

1. Haz fork de este repositorio en tu cuenta de GitHub
2. Ve a **Settings → Secrets and variables → Actions → New repository secret**
3. Añade los tres secrets:

| Secret | Valor |
|--------|-------|
| `ANTHROPIC_API_KEY` | Tu API key de Anthropic (console.anthropic.com) |
| `TELEGRAM_BOT_TOKEN` | Token del bot de BotFather |
| `TELEGRAM_CHAT_ID` | Tu chat ID numérico |

### 3. Activar GitHub Actions

1. Ve a la pestaña **Actions** de tu fork
2. Si aparece el aviso "Workflows are disabled", haz click en **"I understand my workflows, go ahead and enable them"**
3. El bot se ejecutará automáticamente cada hora en punto

### 4. Verificar que funciona

1. Ve a **Actions → ForexSense → Run workflow** para hacer un test manual
2. Revisa el log del job — deberías ver el análisis de cada activo
3. Si hay señal activa, recibirás un mensaje en Telegram

### 5. Ejemplo de mensaje

```
🟢 SEÑAL DE COMPRA — BTC/USDT
💰 Precio: 95840
🎯 Target: 97757 (+2%)
🛑 Stop: 94882 (-1%)
📊 RSI(1H): 38.2  |  MACD: cruce alcista
📈 Tendencia 4H: alcista ✓
⚡ Fuerza: ALTA ⚡
📐 Patrón: bull_flag
🕐 Sesión: Overlap Londres-NY 🔥
🤖 ForexSense • 14:00 UTC
```

## Activos monitoreados

| Activo | Fuente | Horario |
|--------|--------|---------|
| BTC/USDT | Binance (ccxt) | 24/7 |
| ETH/USDT | Binance (ccxt) | 24/7 |
| XAU/USD | yfinance (GC=F) | Lun–Vie |
| EUR/USD | yfinance (EURUSD=X) | Lun–Vie |

## Lógica de señales

- **Filtro diario**: si el activo se movió más de ±2% desde apertura UTC, se pausa
- **Setup técnico**: requiere 3+ condiciones simultáneas (RSI extremo, cruce MACD, posición vs Bollinger)
- **Tendencia 4H**: setups contra-tendencia son rechazados antes de llamar a Claude
- **Patrones**: doble techo/piso, cabeza y hombros, triángulos, flags, pennant
- **Claude confirma**: solo setups con 3+ condiciones TA son enviados a Claude para confirmación final

## Costo estimado

- Infraestructura: **$0** (GitHub Actions free tier)
- Claude API: **~$0–0.10/día** (Haiku, solo cuando hay setups de alta probabilidad)
