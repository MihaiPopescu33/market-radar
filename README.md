# Market Radar

Bot care scanează la fiecare 15 minute 10 piețe (gold, silver, NAS100, S&P 500, petrol, EURUSD, GBPUSD, USDJPY, BTC, ETH) pe H1 și M15. Caută 4 setup-uri clasice și, când apare unul, îl compară cu toate aparițiile lui din trecut. Îți trimite notificare pe telefon (aplicația ntfy) doar dacă setup-ul a avut istoric un rezultat pozitiv.

## Ce primești într-o alertă

```
🟢 LONG GOLD (H1) — trend pullback
Preț la semnal: 3,412.50 (bară închisă 28.09 15:00)
SL: 3,395.10  (-17.40 = 1.5×ATR)
TP: 3,447.30  (+34.80 = 2R)

📊 Istoric (GOLD H1, aceeași direcție): 212 cazuri · 41% câștigătoare · +0.19R/trade · PF 1.31
🔎 Cele mai asemănătoare 25 situații: 52% câștigătoare · +0.52R/trade
✅ Edge prezent în ambele jumătăți ale istoricului
🧭 Trend H1: bullish (în favoare)
📰 Știri cu impact mare: USD Core PCE la 15:30
```

- **Istoric**: de câte ori a apărut exact setup-ul ăsta pe instrumentul și timeframe-ul respectiv și cât a câștigat în medie (în R, adică multipli de risc). +0.19R înseamnă că la un risc de 100 lei ai fi câștigat în medie 19 lei pe trade, după costuri.
- **Situații asemănătoare**: dintre cazurile istorice, le alege pe cele 25 cu contextul cel mai apropiat de acum (RSI, distanța față de EMA200, volatilitate, momentum, ora din zi) și îți arată cum s-au terminat. Asta e partea de „scenariu asemănător”.
- **Stabil**: edge-ul trebuie să existe și în prima, și în a doua jumătate a istoricului. Filtrul ăsta elimină multe „tipare” care au mers doar din noroc.

## Setup-urile

| Setup | Ce caută |
|---|---|
| trend_pullback | Trend clar (EMA50 peste/sub EMA200), prețul atinge EMA20 și închide înapoi în direcția trendului |
| breakout | Închidere peste maximul/sub minimul ultimelor 20 de bare, cu lumânare puternică |
| bb_rsi_reversal | Prețul iese din Bollinger cu RSI sub 30 / peste 70, apoi închide înapoi înăuntru |
| liquidity_sweep | Străpunge maximul/minimul zilei anterioare și închide înapoi (vânătoare de stopuri) |

Toate se testează cu aceleași reguli: intrare la deschiderea barei următoare, SL 1.5×ATR, TP 2R, cost de 0.05R pe trade. Dacă SL și TP se ating în aceeași bară, se consideră pierdere.

## Instalare (circa 15 minute, gratuit)

### 1. Notificările pe telefon (ntfy)
1. Instalează aplicația **ntfy** (de Philipp Heckel) din App Store / Google Play.
2. Apasă **+** → la „Topic name” scrie un nume greu de ghicit, ex. `radar-mihai-8472` → **Subscribe**.
   Oricine știe numele poate citi alertele, de aceea să fie unic. Numele ăsta e „cheia” pe care o pui mai jos în GitHub.

### 2. GitHub (aici rulează botul, fără server)
1. Fă-ți cont pe github.com dacă nu ai.
2. **New repository** → nume `market-radar` → **Public** → Create.
   Public pentru că așa minutele de GitHub Actions sunt nelimitate. Pe un repo privat scanarea la 15 minute depășește limita gratuită de 2.000 de minute pe lună. Numele topicului rămâne secret oricum.
3. **Add file → Upload files** → urcă tot conținutul folderului ăstuia, inclusiv folderul `.github`. Dacă nu vezi `.github`, e ascuns în Finder/Explorer: în Finder apasă Cmd+Shift+. ca să apară.
4. **Settings → Secrets and variables → Actions → New repository secret**:
   - Name: `NTFY_TOPIC` · Secret: numele topicului tău (ex. `radar-mihai-8472`)
5. **Actions** → dacă ți se cere, apasă „I understand my workflows, enable them”.
6. Test: **Actions → test-notificare → Run workflow**. În ~1 minut primești pe telefon „Market Radar e conectat”.
7. **Actions → report → Run workflow**. În 2–5 minute primești raportul cu setup-urile care au edge acum. Din acel moment scanarea pornește automat la fiecare 15 minute.

## Ce face singur

- **La fiecare 15 minute**: scanează, trimite alerte, notează fiecare alertă în `journal.csv` și închide automat alertele vechi când ating SL sau TP.
- **Duminică seara**: backtest complet pe toate combinațiile (10 instrumente × 2 timeframe-uri × 4 setup-uri × long/short = 160). Rezultatul e în `reports/backtest.md` și pe telefon primești top 10 plus scorul real al alertelor din jurnal.

## Setări (`config.py`)

- `INSTRUMENTS`: adaugi sau scoți piețe (simbolurile de pe finance.yahoo.com).
- `SL_ATR`, `TP_R`: cum gestionezi tranzacția.
- `MIN_SAMPLES`, `MIN_EXPECTANCY`: cât de strict e filtrul.
- `SEND_WEAK = True`: primești și setup-urile fără edge, marcate „doar informativ”. Util în primele zile ca să vezi că merge.

## Lucruri de știut

- **Prețurile vin de pe Yahoo** (gold = futures GC=F, întârziere de ~10 min pe futures). CFD-ul din Trading 212 poate fi la câțiva dolari distanță. De aceea alerta îți dă și **distanțele** SL/TP. Aplică-le față de prețul de la broker.
- **M15 are doar 60 de zile de istoric** (limita Yahoo), deci puține cazuri. Pe H1 statisticile sunt mult mai solide (2 ani).
- **Istoricul pozitiv nu garantează nimic.** Cel mai valoros e jurnalul: după 1–2 luni îți arată dacă alertele chiar au câștigat live. Dacă un setup e bun pe backtest și slab în jurnal, îl scoți.
- GitHub poate întârzia uneori scanările programate cu câteva minute când e aglomerat.
