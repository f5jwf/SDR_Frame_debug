# Historique des versions

## 0.6.1 — 13 septembre 2026

- Colonne Hexa brut dans toutes les listes de trames et conservation des codes hexadécimaux nus fournis par rtl_433.

## 0.6.0 — 13 septembre 2026

- Détails communs : nombre d’octets bruts et hexadécimal pour chaque trame. Les rafales CERBERUS validées ne sont plus doublées comme OOK inconnues en mode automatique.

## 0.5.3 — 12 septembre 2026

- Rallongement de la fenêtre de rafale CERBERUS PRO-501 pour conserver les répétitions nécessaires au consensus.

## 0.5.2 — 12 septembre 2026

- Liste déroulante des décodeurs dans l’onglet ISM 868 MHz : Automatique, CERBERUS PRO-501 ou rtl_433 uniquement.

## 0.5.1 — 12 septembre 2026

- La première trame visible est automatiquement sélectionnée et tous ses champs sont développés dans le panneau de détail.

## 0.5.0 — 12 septembre 2026

- Décodeur OOK/PWM adaptatif CERBERUS / Selectronic PRO-501 dans l’onglet ISM 868 MHz : déglitchage, regroupement des ratios, consensus 64 bits et anti-doublon de rafale.

## 0.4.0 — 11 septembre 2026

- Bouton Sauver hex dans chaque espace de travail ; le fichier `.hex` contient une trame brute par ligne.

## 0.3.0 — 10 septembre 2026

- Les paquets OOK/ASK forts mais inconnus de rtl_433 sont conservés comme trames brutes avec leurs impulsions et leur durée, notamment sur 868,3 MHz.

## 0.2.2 — 10 septembre 2026

- Une rupture de l'entrée I/Q de rtl_433 est désormais affichée explicitement au lieu de laisser le statut de décodage actif.

## 0.2.1 — 10 septembre 2026

- Le décodage ISM reçoit désormais l'I/Q brut ; la suppression de la composante centrale reste limitée à l'affichage FFT/waterfall afin de ne pas créer de creux au milieu du canal décodé.

## 0.2.0 — 10 septembre 2026

- Version visible dans le titre et l’en-tête, centralisée avec les métadonnées du paquet.
- Trois onglets Zigbee, ISM 433 MHz et ISM 868 MHz avec profils et trames séparés.
- Bascule asynchrone du récepteur ; conservation des réglages Zigbee existants et des clés en mémoire.
- Réception ISM avec RX et largeur réglables, OOK/ASK et FSK via rtl_433 25.12.
- Liaison binaire par tube nommé Windows, contrôles d’intégrité explicites, JSON/CSV ISM.
- Démonstrations Nexus et LaCrosse, tests d’intégration et spécifications mises à jour.
- Limites : dispositifs reconnus par le moteur uniquement ; octets et niveaux de paquet parfois indisponibles ; qualification RF et essai de deux heures à effectuer.

## 0.1.0 — 9 septembre 2026

Analyseur Zigbee initial avec Pluto/RTL-SDR, FFT/waterfall, tri chronologique, sélection du canal, décodage et export. Optimisations DSP par processus séparé, mémoire partagée et noyaux compilés. Premier commit GitHub : 16ca6c3.
