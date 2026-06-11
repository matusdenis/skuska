========================================================================
             DISK RECOVERY AI - NÁVOD NA SPUSTENIE A NASTAVENIE
========================================================================

Tento dokument vysvetľuje, ako nastaviť, zostaviť a spustiť aplikáciu 
Disk Recovery AI na systéme macOS.

------------------------------------------------------------------------
1. NASTAVENIE ANTHROPIC API KĽÚČA
------------------------------------------------------------------------
Pred prvým spustením musíte aplikácii poskytnúť API kľúč pre Claude:

1. V koreňovom priečinku projektu nájdite alebo vytvorte súbor `.env`
   (ak neexistuje, skopírujte/premenujte `.env.example` na `.env`).
2. Otvorte `.env` v textovom editore.
3. Pridajte alebo upravte nasledujúci riadok s vaším kľúčom:
   
   ANTHROPIC_API_KEY=sk-ant-api03-...váš_skutočný_kľúč...

4. Súbor uložte.

------------------------------------------------------------------------
2. VYTVORENIE APLIKÁCIE DiskRecovery.app (KEĎŽE NIE JE V GITE)
------------------------------------------------------------------------
Aplikácia (.app balík) sa nenachádza v Git repozitári. Musíte ju vygenerovať:

1. Otvorte program Terminál (Terminal) na vašom Macu.
2. Presuňte sa do priečinka s projektom:
   cd "/Users/denismatus/Downloads/recovery data/skuska"
3. Spustite príkaz:
   bash create_app.sh
4. Skript vytvorí súbor "DiskRecovery.app" v koreňovom priečinku projektu.

------------------------------------------------------------------------
3. AKO OTVORIŤ A SPUSTIŤ PROGRAM
------------------------------------------------------------------------
Máte dve možnosti, ako program spustiť:

MOŽNOSŤ A: Cez vygenerovanú aplikáciu DiskRecovery.app (Odporúčané)
1. Nájdite DiskRecovery.app vo Finderi.
2. Ak ju spúšťate prvýkrát a macOS ju zablokuje (nepodpísaná aplikácia):
   Kliknite na ňu pravým tlačidlom myši (alebo dvoma prstami) a vyberte "Otvoriť" (Open).
3. Ak sa aplikácia nespustí správne alebo chcete vidieť výpisy a logy chýb:
   - Kliknite pravým tlačidlom na DiskRecovery.app a zvoľte "Zobraziť obsah balíka" (Show Package Contents).
   - Prejdite do Contents -> MacOS.
   - Dvojklikom spustite súbor s názvom "DiskRecovery" (má čiernu ikonu terminálu). Otvorí sa okno Terminálu s výpismi priebehu.

MOŽNOSŤ B: Cez príkazový súbor Start.command (Jednoduchá alternatíva)
1. V priečinku projektu nájdite súbor "Start.command".
2. Dvojkliknite naň. Automaticky sa otvorí Terminál a naštartuje sa server.

------------------------------------------------------------------------
4. OVLÁDANIE A PRÍSTUP K APLIKÁCII
------------------------------------------------------------------------
* Aplikácia po spustení naštartuje lokálny server na adrese: http://localhost:5001
* Rozhranie by sa malo automaticky otvoriť buď v samostatnom grafickom okne
  alebo vo vašom predvolenom webovom prehliadači (Safari, Chrome atď.).
* Ak sa neotvorí samo, otvorte prehliadač a manuálne zadajte adresu:
  http://localhost:5001
* Pre ukončenie aplikácie stačí zavrieť jej okno alebo zavrieť okno Terminálu, 
  ktoré sa spustením otvorilo.
