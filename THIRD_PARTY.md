# Moteur ISM externe

L’application communique avec **rtl_433 25.12** par un processus et un flux I/Q, sans intégrer son code dans le programme Python.

- Projet officiel et code source : https://github.com/merbanan/rtl_433/tree/25.12
- Distribution Windows : https://github.com/merbanan/rtl_433/releases/tag/25.12
- Licence du moteur : GNU GPL version 2 ou ultérieure, telle qu’indiquée par le projet. Conserver les notices et respecter ses obligations lors de toute redistribution de ses exécutables et dépendances.
- Le script d’installation épingle l’archive officielle x64 et son SHA-256 publié par GitHub. Le dossier runtime est exclu du dépôt.

Les démonstrations sont produites localement à partir des formats radio documentés dans `src/devices/nexus.c` et `src/devices/lacrosse_tx35.c` du moteur. Elles représentent des données artificielles, pas des captures du réseau de l’utilisateur.
