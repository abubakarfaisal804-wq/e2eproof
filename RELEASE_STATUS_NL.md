# Werkelijke releasestatus

## Gebouwd en lokaal gecontroleerd
- Uitvoerbare Python CLI
- Browser-, netwerk- en HTTP-contracten
- Bewijsrapporten en integriteitscontrole
- GitHub composite Action
- `quickstart`, browserinstallatie en browserkeuze
- 54 tests: 53 geslaagd en 1 overgeslagen omdat deze beheerde omgeving localhost-browsernavigatie blokkeert
- 85,24% branch-aware coverage
- Statische audit: 0 fouten en 0 waarschuwingen
- Wheel gebouwd en vanuit het wheel uitgevoerd

## Voorbereid maar nog niet publiek bewezen
- GitHub CI op Windows, Ubuntu en macOS
- Chromium, Firefox en WebKit matrix
- GitHub Marketplace-publicatie
- PyPI en TestPyPI Trusted Publishing
- GitHub artifact attestations
- CodeQL en dependency review

Deze onderdelen bestaan als configuratie, maar mogen pas “geslaagd” worden genoemd nadat ze in de echte openbare repository groen zijn uitgevoerd.

## Niet gedaan
- Geen openbare GitHub-repository
- Geen PyPI-publicatie
- Geen Marketplace-listing
- Geen externe gebruikers
- Geen betaalde klanten
- Geen omzet

## Eerlijke conclusie
Dit pakket is een release candidate voor een openbare alpha. De gebruiker moet nog accountgebonden handelingen uitvoeren: GitHub-authenticatie, repository-eigendom, overeenkomsten, 2FA en PyPI Trusted Publisher-instellingen.
