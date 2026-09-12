# Spécification d’implémentation — Décodeur CERBERUS / Selectronic PRO-501 pour SDR_FRAME_DEBUG

## 1. Objectif

Ajouter à `SDR_FRAME_DEBUG` un décodeur robuste pour les détecteurs d’ouverture CERBERUS / Selectronic PRO-501 en 868 MHz.

Le décodeur doit fonctionner malgré :
- une forte variation du niveau RF ;
- une variation importante du rapport cyclique entre capteurs ;
- une alimentation faible du capteur ;
- des glitches très courts dans les données de capture ;
- des trames partielles ou quelques symboles perdus ;
- plusieurs répétitions de la même trame au sein d’une rafale.

Le décodeur ne doit PAS dépendre d’un seuil temporel fixe pour distinguer les bits.

---

## 2. État des connaissances

### 2.1 Faits suffisamment confirmés

1. Modulation reçue : OOK / ASK avec codage temporel PWM.
2. Une émission est déclenchée lors de la transition contact fermé -> ouvert.
3. La transition ouvert -> fermé ne génère pas de trame.
4. L’ouverture du boîtier (tamper) génère aussi une émission radio.
5. Une rafale contient plusieurs répétitions du même message.
6. La durée d’un symbole est voisine de 1,2 ms.
7. Deux classes de symboles sont présentes :
   - impulsion HIGH relativement courte ;
   - impulsion HIGH relativement longue.
8. Le symbole court en HIGH doit être interprété comme `1`.
9. Le symbole long en HIGH doit être interprété comme `0`.
10. Le rapport cyclique varie fortement selon le capteur et le niveau RF. Le décodage doit donc être adaptatif.
11. Les captures B et C montrent très clairement des groupes de 64 symboles ; la longueur de trame cible à utiliser est donc 64 bits.
12. Les capteurs A, B et C ont des motifs fixes différents : il existe donc une information propre au capteur dans la trame.

### 2.2 Points non encore suffisamment prouvés

Ne PAS figer dans le code :
- la position exacte du champ `sensor_id` ;
- la position exacte du flag `LOW_BAT`;
- un bit distinct `TAMPER`;
- une parité ou un CRC ;
- une compatibilité HCS200 / KeeLoq.

Pour la première version, le programme doit exposer la trame brute et fournir les outils permettant de confirmer ces champs.

---

## 3. Format des fichiers de capture `.hex`

Les captures utilisées ici sont une succession de records de 6 caractères hexadécimaux :

`LLDDDD`

où :
- `LL` = niveau logique sur 8 bits (`00` ou `01`) ;
- `DDDD` = durée sur 16 bits hexadécimaux ;
- la durée est à interpréter dans l’unité temporelle native de SDR_FRAME_DEBUG, correspondant ici approximativement à la microseconde.

Exemple :

`010297000002`

doit être lu comme :
- niveau 1 pendant `0x0297 = 663`
- niveau 0 pendant `0x0002 = 2`

Le parseur doit valider :
- longueur totale multiple de 6 après retrait CR/LF ;
- niveau limité à 0/1 ;
- durée > 0.

---

## 4. Prétraitement / suppression des glitches

Les captures contiennent de nombreux pulses parasites de 1 à quelques µs.

### 4.1 Filtre recommandé

Valeur initiale :

`GLITCH_MAX_US = 50`

Si un pulse de durée <= `GLITCH_MAX_US` est encadré par deux pulses de même niveau :

`A(level X) - glitch(level !X) - B(level X)`

alors fusionner :

`duration = A + glitch + B`

Répéter l’opération jusqu’à stabilisation.

Ne jamais simplement supprimer un pulse sans fusionner ses voisins, sinon le timing total serait modifié.

### 4.2 Paramètre configurable

Prévoir :

```python
glitch_max_us = 50
```

Valeur configurable dans le module protocole.

---

## 5. Reconstruction d’un symbole

Un symbole utile est normalement constitué de :

`HIGH + LOW`

avec :

`Tsymbol = Thigh + Tlow`

Valeur nominale observée :

`Tsymbol ~= 1.2 ms`

### 5.1 Fenêtre initiale large

Ne pas utiliser une fenêtre trop stricte.

Valeurs initiales proposées :

```text
Tsymbol_min = 0.8 ms
Tsymbol_max = 1.6 ms
```

Ces limites servent uniquement à éliminer les événements manifestement impossibles.

### 5.2 Grandeur de décision

Pour chaque couple HIGH/LOW :

```text
ratio = Thigh / (Thigh + Tlow)
```

Le bit ne doit PAS être déterminé par `Thigh` seul.

---

## 6. Décodage adaptatif des bits

C’est le point essentiel pour obtenir un décodeur robuste.

Les captures montrent des ratios très différents :

- capteur A à 9 V : deux populations approximativement autour de 0,22 et 0,55 ;
- capteurs B/C à 9 V : approximativement 0,37 et 0,70 ;
- capteur A à 5 V : approximativement 0,07 et 0,40.

Un seuil fixe du type `ratio < 0.30` est donc interdit.

### 6.1 Méthode recommandée

Pour chaque rafale :
1. collecter tous les `ratio` des symboles temporellement plausibles ;
2. effectuer un clustering robuste en 2 classes ;
3. utiliser par exemple :
   - k-means 1D k=2 ;
   - ou médiane + séparation en deux populations ;
4. obtenir :
   - `Rshort`
   - `Rlong`
5. imposer une séparation minimale, par exemple :

```text
abs(Rlong - Rshort) >= 0.12
```

6. seuil dynamique :

```text
Rthreshold = (Rshort + Rlong) / 2
```

7. mapping :

```text
ratio < Rthreshold  => bit 1
ratio > Rthreshold  => bit 0
```

### 6.2 Score de confiance par symbole

Pour chaque bit, calculer une confiance basée sur la distance au centre de sa classe.

Exemple :

```text
confidence_bit = distance_to_other_cluster /
                 (distance_to_own_cluster + distance_to_other_cluster)
```

Limiter entre 0 et 1.

Un symbole ambigu ne doit pas être forcé silencieusement :
- utiliser `?` en interne ;
- ou confidence faible.

---

## 7. Détection d’une rafale

Une ouverture produit plusieurs répétitions.

La détection de rafale doit être tolérante.

Une rafale peut être commencée lorsqu’un nombre suffisant de symboles compatibles avec ~1,2 ms est détecté.

Elle peut être terminée après :
- un silence suffisamment long ;
- ou une longue zone sans symboles valides.

Valeur de départ possible :

```text
burst_timeout ~= 10 ms
```

Mais ce timeout doit rester configurable.

---

## 8. Synchronisation des trames

### 8.1 Longueur cible

Utiliser :

```text
FRAME_BITS = 64
```

### 8.2 Ne pas supposer un préambule exact

Les captures contiennent beaucoup de zéros en début de bloc, mais l’alignement observé varie légèrement.

Ne pas coder une règle rigide du type :

`35 zéros exacts puis payload`

Pour une première version robuste, synchroniser principalement par répétition.

### 8.3 Méthode de synchronisation recommandée

Sur le flux de bits d’une rafale :

1. tester les 64 offsets possibles ;
2. découper le flux en blocs de 64 bits ;
3. pour chaque offset, calculer la similarité entre blocs ;
4. retenir l’offset maximisant la répétabilité ;
5. construire une trame consensus bit à bit par vote majoritaire pondéré par la confiance.

Alternative encore meilleure :
- recherche de répétitions par corrélation / distance de Hamming sur fenêtres de 64 bits ;
- clusteriser toutes les fenêtres très similaires ;
- choisir le cluster majoritaire.

### 8.4 Distance de Hamming

Tolérer les erreurs.

Valeurs initiales :

```text
max_hamming_distance = 4 bits / 64
```

pour considérer deux trames comme appartenant au même message.

Rendre ce seuil configurable.

---

## 9. Consensus de rafale

Une rafale ne doit produire qu’un seul événement utilisateur.

Pour chaque position 0..63 :

1. réunir tous les bits reçus dans les répétitions alignées ;
2. ignorer les bits marqués inconnus ;
3. faire un vote pondéré par `confidence_bit`;
4. calculer :
   - bit consensus ;
   - confiance par bit ;
   - confiance globale de trame.

Exemple de critère d’acceptation :

```text
au moins 3 répétitions exploitables
ET
confidence_frame >= 0.85
```

Si seulement 1 ou 2 répétitions sont reçues :
- afficher éventuellement la trame en mode DEBUG ;
- ne pas publier d’événement domotique sauf configuration explicite.

---

## 10. Trames de référence actuellement observées

Ces valeurs sont des prototypes de trames brutes alignées sur 64 bits.
Elles servent de jeux de test, PAS encore de définition officielle des champs.

### Capteur A — 9 V

```text
0000000000000000000000000000000000010110001000000000000000001000
```

### Capteur B — 9 V

```text
0000000000000000000000000000000001001101110000000000000000001011
```

### Capteur C — 9 V

```text
0000000000000000000000000000000001000010110000000000000000001011
```

Important :
- l’alignement exact devra être recalculé par le décodeur ;
- le logiciel ne doit pas reconnaître un capteur par comparaison exacte à ces chaînes ;
- ces chaînes servent à vérifier le pipeline de démodulation / clustering / synchronisation.

---

## 11. Identification des capteurs

Tant que le champ `sensor_id` exact n’est pas formellement localisé, utiliser une identification en deux niveaux.

### Niveau 1 — toujours disponible

Publier :

```text
raw_frame_64
```

et un identifiant de fingerprint calculé à partir des bits stables de la trame consensus.

### Niveau 2 — apprentissage

Prévoir une table :

```python
known_sensors = {
    "A": template_A,
    "B": template_B,
    "C": template_C,
}
```

Comparer la trame consensus au template avec un masque permettant d’ignorer les bits d’état.

Le masque ne doit être figé qu’après confirmation expérimentale des bits LOW_BAT / autres états.

Prévoir une commande / option DEBUG permettant d’afficher les bits variant entre deux captures d’un même capteur.

---

## 12. LOW BATTERY

Le détecteur semble transmettre l’information batterie uniquement lors d’une émission provoquée par un événement.

Cependant, la position exacte du flag n’est pas encore suffisamment fiable pour être codée définitivement.

### Exigence V1

Le décodeur doit :
- conserver toutes les trames consensus ;
- permettre une comparaison bit-à-bit ;
- afficher les positions différentes par rapport au template du même capteur à 9 V ;
- exposer un champ :

```text
battery_state = UNKNOWN
```

tant que le mapping n’est pas validé.

### Mode expérimental

Il est acceptable d’ajouter :

```text
battery_state_candidate
changed_bits_vs_reference
```

mais ne pas publier `LOW` comme information domotique certaine avant validation.

---

## 13. Tamper

La capture d’ouverture du boîtier montre une émission du même protocole.

À ce stade, il n’est pas suffisamment démontré qu’un bit distinct permet de différencier :
- ouverture porte ;
- ouverture boîtier.

Donc la V1 doit publier :

```text
event = ALARM
```

et non forcer :

```text
event = DOOR_OPEN
```

Le niveau applicatif peut savoir qu’une émission du détecteur correspond à une condition d’alarme.

---

## 14. API proposée

Créer un module protocole séparé, par exemple :

```text
protocols/cerberus_pro501.py
```

Interface suggérée :

```python
@dataclass
class Pro501DecodeResult:
    valid: bool
    raw_bits: str
    raw_u64: int | None
    repeats: int
    frame_confidence: float
    symbol_confidence: float
    sensor_key: str | None
    event: str               # "ALARM" / "UNKNOWN"
    battery: str             # "OK" / "LOW" / "UNKNOWN"
    changed_bits: list[int]
    timing_us: float
    ratio_short: float
    ratio_long: float
```

Fonctions :

```python
def decode_pro501(edges) -> Pro501DecodeResult | None
def detect_pro501_burst(edges) -> bool
def build_consensus(frames) -> ...
def compare_frames(a, b) -> list[int]
```

Le code spécifique PRO-501 ne doit pas polluer le décodeur générique SDR.

---

## 15. Sortie DEBUG

Exemple :

```text
[PRO501]
valid             : YES
frame_bits         : 64
repeats            : 18
Tsymbol            : 1196 us
ratio_short        : 0.217
ratio_long         : 0.553
cluster_separation : 0.336
confidence         : 0.97
sensor_key         : ...
event              : ALARM
battery            : UNKNOWN
raw                : 0000000000000000000000000000000000010110001000000000000000001000
```

En mode verbose :

```text
repeat 01 : 000...1000 confidence=0.96
repeat 02 : 000...1000 confidence=0.94
repeat 03 : 000...?000 confidence=0.83
consensus : 000...1000 confidence=0.97
```

---

## 16. Anti-doublon

Une seule ouverture produit plusieurs répétitions.

Une rafale validée doit donc générer un seul événement.

Prévoir un mécanisme :

```text
dedup_key = sensor_key + raw_frame_consensus
dedup_window ~= 0.5 à 2 s
```

Valeur initiale proposée :

```text
1 seconde
```

Ne pas supprimer une nouvelle alarme réellement séparée après cette fenêtre.

---

## 17. Tests unitaires obligatoires

Créer un dossier :

```text
tests/pro501/
```

Ajouter les captures réelles fournies comme fixtures.

Tests minimum :

### A. Capteur A 9 V
- décodage valide ;
- 64 bits ;
- consensus stable ;
- plusieurs répétitions fusionnées en 1 événement.

### B. Capteur A 5 V
- le décodage doit encore réussir malgré le déplacement massif du rapport cyclique ;
- aucun seuil ratio fixe ne doit être utilisé.

### C. Capteur A 4,5 / 4,6 V
- le programme ne doit jamais crasher ;
- accepter `low confidence` ou `invalid` si la séparation des classes devient insuffisante ;
- ne pas inventer une trame.

### D. Capteur B 9 V
- décodage valide ;
- résultat distinct de A.

### E. Capteur C 9 V
- décodage valide ;
- résultat distinct de A et B.

### F. Tamper
- reconnaître le protocole ;
- publier au minimum `event=ALARM`.

### G. Glitches
Injecter artificiellement des pulses 1..20 µs dans une trame propre.
Le résultat consensus doit rester identique.

### H. Symboles perdus
Supprimer 1 à 2 symboles dans une répétition.
Les autres répétitions doivent permettre de récupérer le consensus.

### I. Bruit
Ajouter des pulses non conformes avant/après la rafale.
Ils ne doivent pas être interprétés comme une trame valide.

---

## 18. Critères de robustesse

Une trame ne doit être déclarée valide que si plusieurs critères sont simultanément remplis :

1. deux clusters temporels détectables ;
2. séparation des clusters suffisante ;
3. durée symbole cohérente ;
4. répétition de fenêtres 64 bits ;
5. consensus de rafale suffisamment élevé.

Ne jamais décider `PRO501` uniquement parce que `Tsymbol ~= 1.2 ms`.

Score possible :

```text
score =
  0.25 * timing_score +
  0.25 * cluster_score +
  0.30 * repeat_score +
  0.20 * consensus_score
```

Seuil proposé :

```text
score >= 0.80 => valid
0.60..0.80    => debug / probable
< 0.60        => reject
```

---

## 19. Paramètres centralisés

Tous les paramètres doivent être regroupés :

```python
PRO501_FRAME_BITS = 64
PRO501_GLITCH_MAX_US = 50
PRO501_TSYM_MIN_US = 800
PRO501_TSYM_MAX_US = 1600
PRO501_MIN_CLUSTER_SEPARATION = 0.12
PRO501_MAX_HAMMING = 4
PRO501_MIN_REPEATS = 3
PRO501_DEDUP_MS = 1000
PRO501_MIN_CONFIDENCE = 0.85
```

Ils ne doivent pas être dispersés dans le code.

---

## 20. Principe de développement demandé à Codex

Implémenter en deux phases.

### Phase 1 — robuste et sûre
- parseur ;
- deglitch ;
- reconstruction HIGH/LOW ;
- clustering adaptatif ;
- récupération des bits ;
- recherche de périodicité 64 bits ;
- consensus ;
- fingerprint capteur ;
- sortie DEBUG ;
- anti-doublon ;
- tests réels A/B/C.

### Phase 2 — sémantique
Après nouvelles captures :
- déterminer précisément le champ sensor ID ;
- déterminer LOW_BAT ;
- vérifier tamper ;
- ajouter éventuellement CRC/parité.

Ne pas anticiper la phase 2 par des constantes non démontrées.

---

## 21. Règle essentielle

Le décodeur doit être basé sur :

**la géométrie relative des deux populations temporelles + la répétition de trame**

et non sur :

**des valeurs HIGH/LOW fixes apprises sur un seul capteur.**

C’est la condition principale pour qu’il reste fiable avec les capteurs A, B, C et avec une batterie faible.
