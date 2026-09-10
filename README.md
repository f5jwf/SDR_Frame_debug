# SDR Frame Debug

Application Python de réception et diagnostic SDR, développée à partir de `doc/Specification_Application_SDR_Zigbee.docx`. Windows, PySide6 et pyqtgraph. Aucun chemin d’émission RF.

## Démarrage

Double-cliquer sur **lancer.bat**. L’environnement Python 3.12 et les dépendances sont déjà installés dans `.venv` sur cette machine.

```powershell
.\.venv\Scripts\python.exe main.py
# Sans matériel :
.\.venv\Scripts\python.exe main.py --demo
```

Sur une autre machine : Python 3.12, puis `py -3.12 -m venv .venv` et `.\.venv\Scripts\python.exe -m pip install -e ".[hardware]"`. Le pilote du Pluto et la bibliothèque native libiio doivent être installés ; le paquet Python seul ne les remplace pas. Le backend RTL nécessite également sa bibliothèque native librtlsdr et un pilote USB compatible.

## Utilisation

1. Choisir **PlutoSDR**, puis **Détecter** pour choisir l’URI USB ou réseau. L’URI réseau standard proposée est `ip:192.168.2.1`. Un Pluto Rev.C a été détecté et testé en USB sur cette machine.
2. Régler Fc, taux I/Q, gain manuel ou AGC ; cliquer **Démarrer**. **Appliquer** effectue une reconfiguration dans le worker, avec une brève interruption explicite de l’acquisition. Sur Pluto, le gain et le mode AGC sont appliqués directement après 250 ms, sans rouvrir la source. Le gain relu est affiché ; en AGC, le réglage manuel est désactivé.
3. Ajuster SPAN pour zoomer immédiatement sur le spectre et le waterfall. SPAN reste borné par la bande échantillonnée. Déplacer le marqueur RX : il se verrouille sur le canal Zigbee le plus proche. Le bouton **Recentrer sur RX** ramène ce canal au centre du SDR.
4. Sélectionner une trame pour voir ses champs et le dump hexadécimal/ASCII. Le texte brut peut être sélectionné et copié. Double-cliquer une ligne pour la marquer comme favorite.
5. Les filtres et la recherche ne changent pas l’acquisition. **CRC BAD** inclut les trames invalides. **Pause affichage** continue la réception ; les 2 000 dernières trames en attente sont ajoutées à la reprise.
6. **Enregistrer I/Q** crée une paire `.sigmf-meta`/`.sigmf-data` à fréquence fixe. Une reconfiguration clôt la capture. Les données sont des complexes float32 little endian, I puis Q ; prévoir environ 32 Mo/s à 4 MS/s. Un nom déjà utilisé est refusé.
7. **Ouvrir I/Q**, puis sélectionner **Rejeu SigMF** et démarrer. Le fichier détermine Fc et le taux ; les horodatages d’origine sont conservés. Le rejeu s’arrête à la fin.
8. **Exporter trames** écrit les lignes filtrées en JSON, CSV ou PCAP Wireshark. **Sauver session** écrit les trames encore retenues, y compris celles en pause, les paramètres SDR et les compteurs dans un JSON. Ce n’est pas un enregistrement illimité de toutes les trames depuis le démarrage.

Le fichier `examples/zigbee_reference.sigmf-meta` est une référence **synthétique** reproductible : trois trames On/Off (Off, On, Toggle) avec bruit et décalage de fréquence de 18 kHz. Son PCAP est également fourni et a été vérifié avec Wireshark/tshark.

## Décodage et clés

La chaîne comprend translation NCO, filtre FIR avec état, adaptation de cadence, synchronisation SHR/SFD, démodulation différentielle O-QPSK demi-sinus, identification des symboles DSSS, PHR/PSDU et CRC-16 IEEE 802.15.4. Elle préserve les trames coupées entre blocs. La synchronisation de début de paquet et l’estimation d’un décalage de fréquence constant sont implantées ; il ne s’agit pas d’un récepteur avec boucle complète de suivi de dérive d’horloge ou égalisation multipath.

Taux proposés : **2,4 / 2,56 / 4 / 8 / 10 / 12 / 15,36 / 16 / 20 / 30,72 / 61,44 MS/s**. Le décodeur convertit le canal sélectionné vers sa cadence interne de 4 MS/s. Pour RTL avec convertisseur externe : uniquement 2,4 ou 2,56 MS/s, avec une marge RF réduite. Le canal utile entier doit rester dans la bande acquise. Les écarts de lecture du Pluto jusqu’à 4 Hz sont assimilés à la cadence nominale pour le DSP ; la cadence réellement relue reste dans les métadonnées.

Les parseurs couvrent le MAC 2003/2006 courant, les en-têtes Zigbee NWK/APS et des commandes/attributs ZCL usuels : On/Off, lecture/écriture/reporting, valeurs entières, booléens et chaînes. Les versions MAC récentes, la sécurité MAC, le réassemblage APS, les commandes réseau détaillées et les types ZCL non couverts restent explicitement bruts ou signalés.

**Clés Zigbee** accepte une Network Key et une APS Link Key, chacune de 16 octets hexadécimaux. Les clés restent uniquement en mémoire et ne sont pas écrites dans les préférences, logs ou captures. Vider les champs désactive le déchiffrement. Le déchiffrement AES-CCM vérifie le MIC avant d’exposer le contenu ; sans clé ou avec une clé incorrecte, le décodage s’arrête à la couche chiffrée. Les clés dérivées de transport/load et les modes CCM* autres que ENC-MIC32/64/128 ne sont pas implantés. Le JSON de session peut contenir le contenu déchiffré affiché, jamais la clé.

## Réglages et limites

- **FFT / Waterfall** : FFT 1024–8192, fenêtre, moyennage en puissance, intervalle 20–100 ms, historique 30–300 s, palette et dynamique. Les niveaux FFT sont normalisés en dBFS par bin ; ce n’est pas une calibration dBm.
- Waterfall : plus récent en haut, mémoire limitée à 64 Mio, réduction de résolution horizontale si nécessaire. Au plus 600 lignes sont rendues, l’historique complet reste en mémoire. L’axe temporel utilise l’étendue des horodatages ; une cadence irrégulière est représentée approximativement entre les lignes.
- Files : 8 blocs d’acquisition, 2 000 trames vers l’UI, 2 000 trames conservées et 2 000 en pause. Les plus anciennes sont remplacées. Favoriser une trame ne la protège pas de cette limite.
- Les pertes affichées comptent les blocs abandonnés dans la file logicielle. Les APIs matérielles utilisées ne donnent pas de compteur fiable des pertes USB/RF : zéro perte logicielle ne garantit pas une capture matérielle sans lacune. Une discontinuité logicielle réinitialise le démodulateur.
- La réception nominale se déroule hors du thread GUI. Les changements de configuration rouvrent la source et peuvent perdre des trames à cet instant. Arrêter puis démarrer permet de reconnecter après une erreur.
- Les réglages non sensibles et filtres sont dans `%LOCALAPPDATA%\SDRFrameDebug\settings.json`. Logs rotatifs : `application.log`, 2 Mo × 4 fichiers, au même endroit.
- RTL : RF affichée = fréquence du tuner + offset. Exemple : RF 2425 MHz avec convertisseur LO 1800 MHz → tuner 625 MHz. La plage RTL standard est limitée à 0,5–1766 MHz ; celle du Pluto standard à 325–3800 MHz.
- PCAP est fourni (link type 195, FCS inclus) ; PCAPNG et SoapySDR restent des extensions possibles.

## Validation effectuée

- 36 tests automatisés : CRC de référence, démodulation 4/8 MS/s avec bruit/phase/CFO ±100 kHz, blocs de taille impaire, trames consécutives, CRC BAD, longueur maximale, translation NCO, déchiffrement et mauvaise clé, trames tronquées, SigMF/exports, rééchantillonnage RTL, ajout d’un plugin et arrêt/reconfiguration.
- Démonstration avec interface : 61 trames CRC valides en environ cinq secondes, aucune perte logicielle lors de ce contrôle court.
- Pluto Rev.C USB : huit secondes à Fc 2425 MHz et taux relu 3 999 999 éch/s, production du spectre, aucune perte logicielle, arrêt propre. **Aucune trame Zigbee RF n’a été observée pendant cet essai.** Cela valide l’acquisition, pas encore la sensibilité ou le décodage sur le réseau réel.
- Wireshark/tshark : les trois trames du PCAP synthétique ont un FCS valide, source MAC/NWK 0x5678, cluster 0x0006 et commandes ZCL Off/On/Toggle.

Le test de stabilité de deux heures prévu par NF-02 **n’a pas été exécuté**. Le récepteur PHY doit encore être qualifié avec des captures réelles de référence (faible SNR, dérive, interférences, bursts longs). Ces réserves empêchent de considérer tous les critères d’acceptation V1 comme validés.

```powershell
.\.venv\Scripts\python.exe -m pytest -q --basetemp .pytest_validation
.\.venv\Scripts\python.exe tools\soak.py --seconds 7200
```

## Architecture et extension

- `sdr_debug/sdr` : Settings, découverte, Pluto, RTL et source synthétique.
- `sdr_debug/dsp` : workers indépendants, queues, FFT et rééchantillonneur avec état.
- `sdr_debug/protocols/base.py` : Frame et contrat ProtocolPlugin.
- `sdr_debug/protocols/zigbee` : PHY, parseurs et plugin.
- `sdr_debug/capture`, `export`, `ui` : fichiers I/Q, exports et widgets.

Un paquet externe peut enregistrer une classe de plugin via le groupe de points d’entrée `sdr_debug.protocols`. La classe fournit les métadonnées, configure/process_iq/decode/format_summary/get_filters. Aucun changement dans les backends SDR n’est nécessaire. Un test exécute un second plugin de diagnostic via ce mécanisme.

Construction Windows facultative : `build_windows.bat` produit un dossier PyInstaller. Les DLL natives de libiio/librtlsdr doivent rester disponibles sur la machine cible ; le package construit doit être validé sur cette machine.

Références techniques consultées : [API AD936x/Pluto](https://analogdevicesinc.github.io/pyadi-iio/devices/adi.ad936x.html), [guide radio TI CC253x](https://www.ti.com/lit/ug/swru191f/swru191f.pdf), [gestion de sécurité Zigbee dans Wireshark](https://github.com/wireshark/wireshark/blob/master/epan/dissectors/packet-zbee-security.c).


## Vérification du gain avec une porteuse

Les niveaux sont en **dBFS**, référencés aux échantillons numériques du Pluto, et non en dBm. Le spectre indique la puissance par bin FFT ; l’indicateur I/Q total intègre toute la bande. Aucune constante de conversion dBm n’est ajoutée sans étalonnage RF. Une valeur de sortie générateur en dBm et un niveau reçu entre deux antennes ne sont pas directement comparables.

Pour une porteuse à 2450 MHz, régler Fc à 2449,75 MHz : la raie se trouve à +250 kHz et évite le centre DC du récepteur. Garder l’AGC décochée, comparer par exemple 30 puis 50 dB de gain, vérifier le gain **relu** et l’absence de saturation. Avec une porteuse stable et sans compression, le niveau doit suivre approximativement la variation du gain matériel.

La suppression DC logicielle retirait auparavant la moyenne de chaque bloc par défaut, ce qui pouvait effacer une porteuse à Fc. Elle est désormais désactivée par défaut ; l’ancien réglage par défaut est migré au premier lancement de cette version. L’option reste disponible dans FFT / Waterfall, avec un libellé explicite.

Toutes les fenêtres FFT complètes sont maintenant analysées, y compris celles entre deux rafraîchissements. Le détecteur Crête retient les maxima de l’intervalle pour rendre visibles les bursts ; le mode Moyenne reste disponible. Les anciens niveaux de bruit affichés avec une FFT occasionnelle ne sont donc pas directement comparables au détecteur Crête. Le calcul en dBFS n’ajoute aucun gain artificiel. La mémoire des FFT est bornée et le reliquat entre blocs est conservé.

Un changement de gain pendant une capture SigMF est consigné dans les annotations à sa position d’échantillon, sans remplacer le gain initial de la capture. Les pertes physiques éventuelles pendant l’établissement du gain restent soumises aux limites de mesure du backend.


## Cadences Pluto supérieures à 8 MS/s

Choisir la cadence dans MS/s, puis Appliquer. Les cadences au-delà de 8 MS/s sont désormais proposées jusqu’à 61,44 MS/s. Le filtre analogique RX suit la cadence jusqu’à un maximum de 20 MHz, contre une limite logicielle antérieure de 5 MHz. Le SPAN utile est limité par ce filtre et par la cadence ; 61,44 MS/s ne signifie pas 61,44 MHz de bande RF utile sur le Pluto standard.

Le débit **transféré** vers Python est mesuré sur environ une seconde et comparé à la cadence SDR. Un débit sensiblement inférieur est signalé ; cette mesure ne localise pas les pertes matérielles et ne constitue pas une garantie de continuité. Le débit USB et les ressources CPU peuvent empêcher un flux continu aux cadences élevées, même si le Pluto accepte le réglage. Le tampon matériel utilise maintenant 131 072 échantillons à toutes les cadences pour réduire les frais de transfert par bloc (32,8 ms à 4 MS/s).

Les sept nouvelles cadences ont été vérifiées avec une capture synthétique, un canal décalé et des blocs de taille impaire. Aucune qualification du débit continu matériel à ces cadences n’est revendiquée. Pour un seul canal Zigbee, 4 MS/s reste une cadence adaptée ; augmenter la cadence sert surtout à observer une bande plus large.

Spécifications constructeur : https://www.analog.com/en/resources/evaluation-hardware-and-software/evaluation-boards-kits/adalm-pluto.html — 61,44 MS/s maximum et bande instantanée de 20 MHz. Mesures historiques de transfert : https://wiki.analog.com/university/tools/pluto/devs/performance.


## Ordre des trames et pic au centre

Cliquer sur l’en-tête **Date / heure** inverse l’ordre chronologique. La flèche indique le sens ; le tri utilise l’horodatage complet, pas uniquement les millisecondes affichées. Les nouvelles trames et celles libérées après une pause s’insèrent dans cet ordre. Le choix est conservé dans les préférences ; les filtres ne le réinitialisent pas. La limite de 2 000 trames continue d’éliminer les plus anciennes arrivées, quel que soit le tri affiché.

Un pic qui suit systématiquement Fc peut être un résidu DC du récepteur à conversion directe. L’option de suppression DC est désactivée par défaut pour préserver les porteuses réelles au centre. Pour confirmer l’origine d’un pic, modifier légèrement Fc : un signal RF fixe reste à sa fréquence absolue, tandis qu’un résidu DC suit Fc. L’option FFT / Waterfall → Supprimer la porteuse au centre (DC) retire la moyenne des blocs et peut atténuer ce résidu, mais aussi un vrai signal centré. Aucun réglage de correction DC n’a été changé automatiquement à l’occasion de l’ajout du tri.

## Largeur du canal RX et commande DC

Une zone rectangulaire jaune translucide indique la largeur nominale du canal du plugin sur le spectre et le waterfall. Pour Zigbee, elle couvre RX ±1 MHz. Le trait central reste déplaçable ; la zone suit le canal sélectionné et ne modifie pas le SPAN. Cette zone représente les 2 MHz du canal Zigbee, pas une coupure abrupte de la réponse réelle des filtres FIR.

Dans FFT / Waterfall, la commande de suppression DC porte désormais son propre libellé cliquable et un indicateur de 18 pixels contrasté. Le réglage est appliqué à la configuration courante, même si le backend a retourné un nouvel état pendant que le dialogue était ouvert. L’activation et la désactivation sont vérifiées avec clic sur le texte, application pendant la réception et sauvegarde des préférences.


## Optimisation de la réception continue

L’interface lance le DSP dans un processus séparé. L’acquisition attend la préparation des noyaux compilés avant d’ouvrir la source. Une file bornée de 64 blocs utilise 64 Mio de mémoire partagée pour les I/Q ; seuls les paramètres et indices passent par le canal interprocessus. Un bloc n’est réutilisé qu’après sa copie par le consommateur. Ce tampon absorbe environ deux secondes de retard ponctuel à 4 MS/s ; il ne compense pas un débit de calcul durablement insuffisant. L’arrêt vide les blocs acceptés avant de terminer le DSP.

La translation du canal réutilise son oscillateur. Le FIR et la corrélation SHR emploient de petites FFT groupées avec recouvrement ; les coefficients et le seuil de corrélation de 0,78 sont conservés. Numba compile les calculs de phase, de normalisation et de décision des symboles, sans seuil de puissance destiné à ignorer les signaux faibles. Après une discontinuité, seuls les états temporels sont effacés, sans reconstruire les filtres et les modèles.

Le waterfall conserve un historique borné en indices de palette sur 8 bits, calculés uniquement pour chaque nouvelle ligne. Son rendu est limité à 10 images/s ; les fenêtres FFT continuent d’être traitées. Une modification de l’échelle de couleur réinitialise cet historique. Le spectre conserve ses valeurs flottantes en dBFS.

La ligne **DSP** indique le temps de calcul moyen par bloc, sa durée radio et l’occupation de la file. Une charge durablement supérieure à 100 % signifie que le traitement ne suit pas. Une file qui se remplit progressivement annonce des pertes. Le compteur **Blocs perdus (logiciel)** reste actif et ne compte que les blocs refusés par cette file ; il ne mesure pas les pertes USB ou matérielles. Un débit transféré inférieur à la cadence radio peut donc signaler un problème distinct, même avec zéro perte logicielle.

Le nouveau moteur nécessite Numba, installé dans l’environnement du projet et déclaré dans les dépendances. Le premier démarrage peut prendre quelques secondes pour compiler les noyaux ; la capture commence ensuite. Relancer l’application avec `lancer.bat` pour charger cette version. Pour commencer la validation sur Pluto, sélectionner 4 MS/s et Recentrer sur RX afin que le canal reste entièrement dans la bande, puis Appliquer.

Le benchmark ci-dessous affiche réellement les widgets dans un rendu Qt hors écran et utilise une source synthétique, sans accéder au SDR ni modifier les préférences utilisateur. La durée demandée commence après la préparation du processus DSP. Il ne remplace pas une qualification RF/USB ni un test prolongé.

```powershell
.\.venv\Scripts\python.exe tools\performance_check.py --seconds 60 --rate 4 --offset 1 --output tools\performance_final_4msps.json
```

Validation avant publication : **50 tests passent** (10 septembre 2026), notamment équivalence numérique des filtres et des noyaux compilés, réutilisation des tampons partagés, vidage du rejeu en fin de fichier et arrêt sur erreur. Le dernier benchmark d’une minute à 4 MS/s a décodé 736 trames valides avec 12 blocs perdus, avec le tampon intermédiaire de 32 blocs. Son rapport historique est conservé dans `tools/performance_final_4msps.json`. Le tampon courant de 64 blocs passe les tests fonctionnels mais n’a pas encore fait l’objet du même benchmark prolongé. Aucune garantie de zéro perte sur le Pluto n’est revendiquée.
