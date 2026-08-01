# E2EProof — Nederlandse start

E2EProof controleert niet alleen wat een webinterface zegt, maar ook of de bedoelde actie werkelijk in de backend plaatsvond.

## Snelste test

Na publicatie op PyPI:

```powershell
py -m pip install e2eproof
e2eproof quickstart
```

De opdracht installeert na toestemming Chromium wanneer dat ontbreekt, start een echte lokale testapp, voert een browseractie uit, leest de backend onafhankelijk terug en opent het bewijsrapport.

## Eigen app

```powershell
e2eproof init e2eproof.yaml
e2eproof validate e2eproof.yaml
e2eproof run e2eproof.yaml
```

Dit is een alpha developer-tool. Het is geen cloudproduct, geen volledige securityaudit en geen garantie voor iedere applicatie.
