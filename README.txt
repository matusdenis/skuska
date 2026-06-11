========================================================================
             DISK RECOVERY AI - NÁVOD NA SPUSTENIE A NASTAVENIE
========================================================================

Tento dokument vysvetľuje, ako funguje, ako sa nastavuje a ako sa spúšťa 
aplikácia Disk Recovery AI na systéme macOS.

========================================================================
 O APLIKÁCII (AKO TO FUNGUJE)
========================================================================
Disk Recovery AI je pokročilý, multi-agentový systém riadený umelou 
inteligenciou (Claude od Anthropic), ktorý slúži na rekonštrukciu a obnovu 
dát z poškodených diskov, diskových obrazov (.img, .dmg) alebo RAID polí.

Proces obnovy prebieha v 5 nadväzujúcich fázach:

1. SKENOVANIE (Scanner - `scanner.py`):
   Vykonáva nízkoúrovňové (raw) čítanie disku. Vyhľadáva známe signatúry 
   súborových systémov (napr. APFS) a hlavičiek súborov. Ak sa zistí prítomnosť 
   APFS, spúšťa sa aj špecializovaný hĺbkový APFS skener (`apfs.py`).

2. AI ANALÝZA (Agent 1 - MapAnalystAgent v `agents.py`):
   Zasiela výsledky skenovania do Anthropic Claude, ktorý identifikuje 
   pôvodné rozloženie partícií a hľadá zhluky súborových dát.

3. AI PREDIKCIA (Agent 2 - MapPredictorAgent v `agents.py`):
   Odhaduje rozsah poškodenia, fragmentáciu a dopočítava chýbajúce alebo 
   prepísané časti partičnej mapy disku.

4. AI PLÁN OBNOVY (Agent 3 - RecoveryPlannerAgent v `agents.py`):
   Vytvorí prioritizovaný zoznam krokov pre obnovu dát (napr. ktoré sektory 
   kopírovať, akú metódu použiť a aká je pravdepodobnosť úspechu).

5. EXEKÚCIA (Executor - `carver.py`):
   Fyzicky extrahuje a rekonštruuje (carving) nájdené súbory a priečinky 
   a ukladá ich do cieľového priečinka.

------------------------------------------------------------------------
 ŠPECIÁLNY REŽIM: REKONŠTRUKCIA RAID / MULTI-DEVICE
------------------------------------------------------------------------
Ak zadáte cesty k viacerým diskom naraz (oddelené čiarkou), systém spustí 
špeciálny režim:
* Oskenuje začiatok každého disku.
* AI analyzuje vzory dát a rozhodne, či ide o JBOD alebo RAID0 (Stripe).
* Spojí disky do jedného zrekonštruovaného diskového obrazu `.img`.
* Nájde APFS hlavičku a automaticky opraví tabuľku partícií (GPT).
* Výsledný `.img` súbor potom stačí v macOS jednoducho otvoriť dvojklikom 
  a súbory sa pripoja aj s pôvodnými názvami a štruktúrou priečinkov.

========================================================================
 INŠTALÁCIA A NASTAVENIE
========================================================================

------------------------------------------------------------------------
1. NASTAVENIE ANTHROPIC API KĽÚČA
------------------------------------------------------------------------
Keďže aplikácia využíva inteligenciu Claude na analýzu a plánovanie, 
musíte nastaviť API kľúč:

1. V koreňovom priečinku projektu nájdite alebo vytvorte súbor `.env`
   (ak neexistuje, premenujte `.env.example` na `.env`).
2. Otvorte ho v textovom editore.
3. Pridajte váš kľúč v tomto tvare (bez úvodzoviek):
   
   ANTHROPIC_API_KEY=sk-ant-api03-...váš_skutočný_kľúč...

4. Uložte súbor.

------------------------------------------------------------------------
2. VYTVORENIE APLIKÁCIE DiskRecovery.app (KEĎŽE NIE JE V GITE)
------------------------------------------------------------------------
Aplikácia (.app balík pre macOS) sa nenachádza v Git repozitári. Vygenerujete 
ju nasledovne:

1. Otvorte program Terminál (Terminal) na Macu.
2. Presuňte sa do priečinka projektu:
   cd "/Users/denismatus/Downloads/recovery data/skuska"
3. Spustite skript:
   bash create_app.sh
4. V priečinku sa objaví nová ikona "DiskRecovery.app".

========================================================================
 AKO OTVORIŤ A SPUSTIŤ PROGRAM
========================================================================

Máte dve alternatívne možnosti spustenia:

MOŽNOSŤ A: Cez vygenerovanú aplikáciu DiskRecovery.app (Odporúčané)
1. Nájdite DiskRecovery.app vo Finderi.
2. Ak ju spúšťate prvýkrát a macOS ju zablokuje (nepodpísaná aplikácia):
   Kliknite na ňu pravým tlačidlom myši (alebo dvoma prstami) a vyberte "Otvoriť" (Open).
3. Ak sa nespustí správne alebo chcete vidieť výpisy chýb (Logs):
   - Kliknite pravým tlačidlom na DiskRecovery.app a zvoľte "Zobraziť obsah balíka" (Show Package Contents).
   - Prejdite do Contents -> MacOS.
   - Spusťte súbor "DiskRecovery" (ikona čierneho terminálu). Otvorí sa okno Terminálu s výpisom detailov na pozadí.

MOŽNOSŤ B: Cez príkazový súbor Start.command (Jednoduchá alternatíva)
1. V priečinku projektu nájdite súbor "Start.command".
2. Dvojkliknite naň. Automaticky sa otvorí Terminál a naštartuje sa pythonovský server.

========================================================================
 OVLÁDANIE A WEB-ROZHRANIE
========================================================================
* Po spustení aplikácia naštartuje lokálny server na adrese: http://localhost:5001
* Automaticky sa otvorí samostatné grafické okno aplikácie (alebo váš 
  webový prehliadač). Ak sa neotvorí, zadajte adresu manuálne do prehliadača.
* V rozhraní vypĺňate nasledovné polia:
  - Cesta k zariadeniu/obrazu (napr. `/dev/disk2` alebo `test_disk.img`).
  - Cieľový adresár (kam sa uložia obnovené dáta).
  - Maximálna veľkosť skenu (napr. `200M`, `2G` alebo ponechajte prázdne pre celý disk).
* Kliknutím na "Spustiť obnovu" môžete sledovať priebeh jednotlivých 
  fáz a odpovede AI agentov v reálnom čase.
* Ukončením okna programu alebo terminálu sa vypne aj lokálny server.
