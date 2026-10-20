# Oppsett og tilpasning

## Krav

- Linux med et V4L2-webkamera.
- En kjørende Hyprland-økt med Lua-API-et (`hyprctl eval`; testet med 0.56).
- [uv](https://docs.astral.sh/uv/), som håndterer prosjektets Python-miljø.

Kjør i en terminal i Hyprland, uten sudo. Startskriptet fungerer fra alle mapper. Eksemplene nedenfor forutsetter at du står i prosjektmappen.

## Første oppstart

```sh
uv sync --locked
./lean-scale setup
./lean-scale devices
./lean-scale calibrate
./lean-scale run --dry-run
```

Kalibreringen bruker som standard kamera `0` og skjermen som har fokus. Slik velger du selv:

```sh
./lean-scale calibrate --camera /dev/video0 --monitor HDMI-A-1
```

Se mot kameraet både når du sitter som vanlig, og når du lener deg tilbake. Kalibreringen slår på webkameraet, men endrer ikke skaleringen. Ustabile målinger eller for liten forskjell mellom stillingene blir avvist. Skaleringen når du lener deg tilbake, blir som standard omtrent 25 % større enn den gjeldende. Verdien tilpasses slik at skjermens logiske mål blir hele piksler.

Stopp prøvekjøringen med **Ctrl+C**, og aktiver faktisk skalering med `./lean-scale run`. Kalibrer på nytt hvis du endrer vanlig skalering, kameraplassering, kamerazoom eller sittestilling.

## Styring og gjenoppretting

```sh
./lean-scale status
./lean-scale toggle
./lean-scale pause
./lean-scale resume
./lean-scale stop
./lean-scale restore
```

Pause frigjør webkameraet og forsøker å gjenopprette skaleringen du startet med. Når du fortsetter, åpnes kameraet igjen. Ctrl+C, SIGTERM, stoppkommandoen og håndterte feil forsøker også å gjenopprette skaleringen. `restore` gjenoppretter den lagrede skaleringen etter en ukontrollert avslutning, som `kill -9`. Stopp bakgrunnsprosessen før du bruker kommandoen. Bare én prosess for kjøring, kalibrering eller gjenoppretting kan holde låsen om gangen.

Hvis programmet oppdager at skaleringen er endret utenfra før en overgang eller gjenoppretting, unngår det å overskrive endringen. Den valgte skjermen må være tilkoblet for at gjenoppretting skal fungere.

## Hurtigtast i Hyprland

Legg dette til i Lua-konfigurasjonen din. Bytt ut `/absolute/path/to/lean-scale` med den absolutte stien til prosjektmappen:

```lua
hl.bind("SUPER + SHIFT + Z", hl.dsp.exec_cmd("/absolute/path/to/lean-scale/lean-scale toggle"))
```

For valgfri automatisk oppstart **etter testing og kalibrering** kan du legge dette inn i oppstartshåndteringen din:

```lua
hl.on("hyprland.start", function()
    hl.exec_cmd("/absolute/path/to/lean-scale/lean-scale run")
end)
```

Ingen av kodeeksemplene installeres automatisk.

**Bruk en egen skjermregel for den valgte skjermutgangen**, ikke bare en regel basert på jokertegn eller beskrivelse. Endringer under kjøring bruker `hl.monitor({output=..., scale=...})`, som oppdaterer regelen for akkurat denne utgangen. Uten en tilsvarende regel kan en ny regel arve standardverdier. Konfigurer for eksempel `output = "HDMI-A-1"` med skjermmodusen, plasseringen og skaleringen du vanligvis bruker.

Programmet endrer ingen av Hyprlands konfigurasjonsfiler. Hvis du laster konfigurasjonen på nytt, kan den overstyre skaleringen som er satt under kjøring.

## Slik fungerer sporingen

YuNet finner ansikter og punkter ved øynene lokalt på CPU-en, med omtrent åtte målinger per sekund. Avstanden mellom øynene i forhold til bildebredden brukes til å anslå avstand. Dette er ikke en full analyse av kroppsholdning eller en måling i centimeter.

- Utjevning, hysterese og et krav om **1,8 sekunder i stabil sittestilling** reduserer veksling mellom nivåene. Utjevningen gir noe ekstra responstid.
- Ved korte avbrudd i sporingen beholdes gjeldende nivå. **Fem sekunder uten pålitelig sporing** setter skaleringen tilbake til normalen.
- Flere ansikter, avkuttede eller små ansikter og tydelige hodedreininger ignoreres. Mindre dreininger kan fortsatt se ut som at du flytter deg unna.
- Ved kamerafeil stopper programmet og forsøker å gjenopprette skaleringen.
- Bare den kalibrerte skjermen styres. Andre skjermer kan flytte seg når Hyprland beregner et automatisk skjermoppsett på nytt.
- Ønsket skalering kontrolleres mot verdien skjermen rapporterer. Hvis endringen blir avvist, forsøker programmet å sette skaleringen tilbake.

Endret skjermskalering påvirker størrelsen og plasseringen til vinduene, endrer tilgjengelig arbeidsplass og kan gi kortvarig flimring. XWayland-programmer kan bli uskarpe. En prøvekjøring uten skjermendringer kan ikke fortelle deg om selve overgangen vil føles behagelig.

## Konfigurasjon

Kalibreringen lagrer innstillingene i `~/.config/lean-scale/config.json` og følger `XDG_CONFIG_HOME` hvis den er satt. Slik bruker du en annen fil:

```sh
./lean-scale --config /path/to/config.json calibrate
./lean-scale --config /path/to/config.json run
```

Endre innstillingene mens bakgrunnsprosessen er stoppet. Tall i JSON-filen bruker punktum som desimalskilletegn:

| Felt | Standardverdi | Betydning |
| --- | --- | --- |
| `monitor`, `camera` | valgt ved kalibrering | Fast skjermutgang og kameraindeks eller enhetssti |
| `normal_eye`, `leaned_eye` | målt | Normalisert avstand mellom øynene for hver sittestilling |
| `normal_scale`, `leaned_scale` | valgt | Vanlig og forstørret skjermskalering |
| `fps` | 8 | Antall kameramålinger per sekund |
| `dwell` | 1.8 | Påkrevd tid i sammenhengende stabil stilling, i sekunder |
| `smoothing` | 0.6 | Tidskonstant for utjevning, i sekunder |
| `hysteresis` | 0.15 | Dødsone rundt midtpunktet mellom de kalibrerte stillingene |
| `lost_timeout` | 5 | Sekunder uten pålitelig sporing før vanlig skalering gjenopprettes |

Velg ønsket skalering når du lener deg tilbake med for eksempel `./lean-scale calibrate --lean-scale 1.6`. Hvis verdien gir brøkdeler av logiske piksler, foreslås et alternativ. Aktiv skalering må samsvare med `normal_scale` ved oppstart.

Modellen og gjenopprettingsfilen lagres i `~/.local/share/lean-scale/` og følger `XDG_DATA_HOME` hvis den er satt. Den private kontrollsocketen ligger i `$XDG_RUNTIME_DIR/lean-scale/`, eller i en privat mappe for brukeren under `/tmp` hvis variabelen mangler. Ingen kamerabilder lagres. Bare `setup` laster ned ansiktsmodellen. Selve sporingen trenger ikke nettverkstilgang. Se [modellkilde og lisens](../THIRD_PARTY.md).

## Feilsøking

- **Kameraet kan ikke åpnes:** Prøv en annen kameraenhet fra `devices`. Noen enheter leverer metadata eller infrarøde bilder. Lukk andre kameraprogrammer og sjekk enhetstillatelsene. Kameraadresser på nettet og videofiler støttes ikke.
- **For få målinger:** Sørg for bedre lys, se mot kameraet og ha bare ett ansikt i bildet. Svært små ansikter eller stor avstand kan gjøre sporingen vanskelig.
- **Skaleringen avviker fra kalibreringen:** Gjenopprett vanlig skalering eller kalibrer på nytt med ønsket vanlig skalering.
- **Gammel gjenopprettingsfil:** Stopp bakgrunnsprosessen, koble til den valgte skjermen om nødvendig, og kjør `restore`.
- **Treg respons:** Prøv `dwell: 1.0` og `smoothing: 0.4`. Raskere innstillinger gir større risiko for veksling mellom nivåene.
- **Uønskede vindusendringer:** Sett på pause eller stopp. Automatisk skjermskalering passer ikke nødvendigvis måten du jobber på.

## Utvikling

```sh
uv sync --locked
uv run pytest
uv run ruff check .
uv run ruff format --check .
```

Testene bruker syntetiske målinger, simulert skjermstyring og private testsocketer, aldri webkameraet eller faktiske skjermendringer. Lasting av modellen og kjøring av ansiktsdetektoren er også kontrollert med et syntetisk svart bilde. Kalibrering av faktisk sittestilling og reelle skjermoverganger må testes manuelt.
