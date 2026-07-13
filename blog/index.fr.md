---
title: "Un téléchargeur de podcasts qui ne fait pas confiance au code de sortie 0"
description: "Comment un pipeline yt-dlp auto-hébergé transforme des vidéos web en bibliothèque Audiobookshelf tout en gardant fichiers, métadonnées, files d’attente et workers concurrents cohérents."
date: 2026-07-13
image: images/cover-podcast-pipeline.png
categories: ["Computer Science", "Data Engineering"]
---

# Un téléchargeur de podcasts qui ne fait pas confiance au code de sortie 0

Je voulais un petit service capable de surveiller une chaîne YouTube, de retirer les segments sponsorisés et de déposer les épisodes terminés dans Audiobookshelf. Formulé ainsi, le projet ressemble à un simple wrapper autour d’une commande. En pratique, l’essentiel du travail concerne tout ce qui peut mal se passer autour de cette commande.

`yt-dlp` se charge de l’extraction. SponsorBlock fournit des plages temporelles maintenues par la communauté pour les segments de sponsoring et d’autopromotion. `ffmpeg` recopie l’audio tout en mettant ses tags à jour. Ces outils font bien le travail multimédia. L’application doit encore déterminer si l’épisode existe réellement, s’il est prudent de marquer l’URL comme terminée et ce qui se passe lorsque deux processus du scheduler voient le même élément.

La leçon de conception la plus utile tient en une phrase : la réussite d’un sous-processus est un indice, pas la transition d’état elle-même.

## D’une URL à un élément de la bibliothèque

La file d’attente accepte trois types d’entrée : une URL directe, une chaîne YouTube ou une playlist YouTube. Les chaînes et playlists sont développées en vidéos concrètes. Les URL directes restent des tâches ponctuelles. La politique de sélection réduit ensuite les candidats : les publications d’une chaîne peuvent attendre un âge minimal, les Shorts sont ignorés et les playlists sont limitées au nombre configuré d’entrées récentes.

Pour YouTube, le téléchargement demande à SponsorBlock de retirer les catégories `sponsor` et `selfpromo`. Le traitement des autres sites est volontairement plus prudent : un seul élément, sans option SponsorBlock et sans développement de playlist. Les cookies peuvent être utilisés dès le premier essai ou seulement en repli, mais uniquement pour YouTube.

![Le pipeline complet, de l’URL à la bibliothèque](images/pipeline-flow.png)

Le schéma sépare trois préoccupations que l’on confond facilement. La politique de source décide *quoi* tenter. La preuve locale établit si la tentative a produit un artefact exploitable. L’état durable ne change qu’après cette preuve et la publication du fichier.

Le répertoire de travail et la bibliothèque finale sont également distincts. `yt-dlp` écrit les fichiers partiels, miniatures et fichiers convertis dans un dossier de travail propre à la source. Seul un MP3 dont les tags ont été écrits rejoint le répertoire lu par Audiobookshelf. Après un échec, les fichiers temporaires sont supprimés, sauf dans un cas de récupération précis où un MP3 existant peut être conservé pour retenter l’écriture des métadonnées.

## Définir la réussite à partir du système de fichiers

Un code de sortie nul ne prouve pas qu’un nouveau MP3 est apparu. Un extracteur peut conclure que l’élément existe déjà, réutiliser un chemin ou terminer sans produire l’artefact attendu par l’application. Le téléchargeur prend donc un instantané de tous les MP3 présents sous le répertoire de travail avant et après chaque tentative.

Pour un chemin MP3 $p$, soit $m(p)$ son heure de modification dans le système de fichiers, en nanosecondes, et $z(p)$ sa taille en octets. L’état enregistré est la paire ordonnée

$$
s(p) = \bigl(m(p), z(p)\bigr).
$$

Soit $B$ l’ensemble des chemins MP3 dans l’instantané pris avant la commande et $A$ l’ensemble correspondant après celle-ci. L’ensemble $C$ des fichiers modifiés est

$$
C = \left\{p \in A : p \notin B \;\lor\; s_A(p) \ne s_B(p)\right\}.
$$

Ici, $s_A(p)$ est l’état du chemin $p$ après la tentative et $s_B(p)$ son état avant celle-ci. Le chemin normal de réussite exige à la fois un code de sortie nul et au moins un chemin dans $C$. Vérifier l’heure de modification et la taille détecte aussi bien un nouveau fichier qu’un fichier existant dont le contenu a été remplacé.

L’implémentation reste volontairement simple :

```python
def _detect_changed_audio_files(
    self,
    before_snapshot: AudioSnapshot,
    after_snapshot: AudioSnapshot,
) -> list[Path]:
    """Return MP3 files created or changed during one command."""
    changed_files: list[Path] = []
    for file_path, updated_state in after_snapshot.files.items():
        previous_state = before_snapshot.files.get(file_path)
        if previous_state is None or updated_state != previous_state:
            changed_files.append(file_path)

    return sorted(changed_files)
```

Il existe une seule règle de récupération, assez stricte. Si les instantanés avant et après sont identiques, que la commande renvoie zéro et qu’un seul MP3 existe déjà dans le répertoire cible, le service peut retenter l’écriture des métadonnées sur ce fichier. Cela couvre un lancement précédent où l’audio a été téléchargé, mais où l’écriture des tags a échoué. S’il existe plusieurs MP3 possibles, le service refuse de deviner.

## Les métadonnées font partie de la transaction

Audiobookshelf a besoin de davantage que des octets audio. Après l’extraction, le service inscrit trois informations de provenance dans le MP3 :

- l’heure locale de fin du téléchargement dans le tag `date` ;
- l’URL source normalisée dans le tag `comment` ;
- le nom résolu de la chaîne dans les tags `artist` et `album`, lorsqu’il est disponible.

Cette heure locale sert également d’horloge de rétention. Elle évite de confondre la date de publication de la vidéo avec la date d’entrée du fichier dans la bibliothèque locale.

La réécriture comporte une contrainte discrète, mais importante. `ffmpeg` a besoin d’une sortie temporaire. Remplacer ensuite le chemin final par ce fichier temporaire peut changer l’inode du fichier. Un inode est l’identité qu’utilise le système de fichiers derrière un chemin ; un observateur de bibliothèque peut donc interpréter ce remplacement comme la disparition d’un élément suivie de l’arrivée d’un autre. Le writer crée plutôt un fichier temporaire caché qui n’a pas l’extension `.mp3`, recopie les octets réécrits dans le MP3 d’origine, puis supprime le fichier temporaire. Le chemin et l’inode d’origine survivent.

La rétention choisit de ne pas supprimer en cas de doute. Elle ne vise que les dossiers de chaînes YouTube encore suivies, jamais les playlists ni les téléchargements ponctuels. Un fichier n’est admissible que si sa date de fin et son URL source intégrées sont toutes deux lisibles. Si un tag manque ou est mal formé, le service garde le MP3, car il ne pourrait pas mettre l’archive à jour de façon sûre après la suppression.

![Les barrières de fiabilité avant toute mutation ou suppression](images/reliability-gates.png)

Cette asymétrie est intentionnelle : une incertitude au téléchargement laisse la tâche retentable, tandis qu’une incertitude lors de la suppression laisse les données intactes. Ce ne sont pas les mêmes pannes, donc leurs valeurs par défaut ne devraient pas être les mêmes.

## L’idempotence exige un verrou autour de la partie lente

Les vidéos issues d’une chaîne ou d’une playlist sont inscrites dans `downloaded_urls.txt`. Cette archive rend les sondages répétés idempotents : revoir la même URL normalisée ne doit pas déclencher un second téléchargement.

Une séquence rapide du type « vérifier le fichier, télécharger, puis ajouter l’URL » reste vulnérable à une course. Deux workers peuvent effectuer la vérification avant que l’un des deux ait ajouté l’URL. Le code conserve un verrou exclusif pendant la détection du doublon, la tentative de téléchargement, qui est lente, et l’ajout final en cas de réussite :

```python
if use_archive:
    with locked_downloaded_url_archive(self.downloaded_urls_file) as archive:
        if archive.contains(normalized_url):
            self._downloaded_urls.add(normalized_url)
            return normalized_url, True

        result_url, success = self._download_video_unlocked(
            normalized_url,
            index,
            total,
            target_final_output_dir,
            target_work_dir,
        )
        if success:
            archive.append_success(normalized_url)
            self._downloaded_urls.add(normalized_url)
        return result_url, success
```

En général, je me méfierais d’un verrou conservé pendant un téléchargement réseau. Ici, il protège un invariant précis de l’archive, et un téléchargement concurrent en double coûte davantage que l’attente. La suite de tests démarre deux instances du téléchargeur sur la même URL développée et vérifie que `yt-dlp` n’est appelé qu’une fois.

La file d’attente, l’archive, la liste des dérogations ponctuelles à la limite d’âge et le journal d’activité du navigateur restent de simples fichiers texte. Des verrous partagés protègent les lectures ; des verrous exclusifs protègent les opérations de lecture-modification-écriture. Le déploiement reste ainsi facile à inspecter et à sauvegarder, sans prétendre que des écritures texte non coordonnées seraient sûres.

## Ce que la suite de tests établit

J’ai lancé la suite de régression hors ligne le 13 juillet 2026. Les 184 tests ont réussi en 9,32 secondes. Il s’agit de tests comportementaux fondés sur des répertoires temporaires et des sous-processus simulés, pas d’un benchmark de débit.

| Frontière vérifiée | Preuve apportée par la suite |
|---|---|
| Détection des artefacts | Un MP3 nouveau ou remplacé compte ; un code de sortie nul sans MP3 ne compte pas |
| Publication sûre | Le MP3 terminé passe de l’espace de travail à la bibliothèque ; les artefacts temporaires sont supprimés |
| Métadonnées | La date et l’URL source sont écrites ; l’inode du MP3 final est préservé |
| Concurrence | Les lecteurs et writers de l’archive se sérialisent ; deux workers ne téléchargent qu’une fois une même URL développée |
| Rétention | Seuls les fichiers de chaîne admissibles sont supprimés ; l’absence de métadonnées conserve le fichier |
| Politique de source | SponsorBlock reste propre à YouTube ; URL directes, chaînes, playlists, Shorts, limites d’âge et cookies suivent des règles distinctes |
| Interface web | Mots de passe, sessions, jetons contre la falsification de requête intersite, confiance envers le proxy, import de cookies et mutation de la file ont une couverture de régression |

La falsification de requête intersite, ou Cross-Site Request Forgery (CSRF), consiste à pousser un navigateur à soumettre une action authentifiée à l’insu de l’utilisateur. L’interface utilise des jetons de connexion à usage unique et des jetons propres à chaque session pour les formulaires qui modifient l’état, en plus d’un mot de passe haché et d’en-têtes de navigateur restrictifs. C’est une protection raisonnable pour une interface d’administration personnelle, pas une transformation du service en plateforme multi-utilisateur.

Le dépôt contient aussi, à la racine, un smoke test SponsorBlock qui appelle réellement le réseau. Il importe le paquet `yt-dlp`, installé séparément, et contacte des services externes. Je ne l’ai pas inclus dans le résultat des 184 tests hors ligne : sans ce paquet optionnel, la collecte de tout le dépôt s’arrête dès l’import. Sur un vrai déploiement, ce test devrait être lancé séparément lorsque `yt-dlp`, `ffmpeg`, les cookies et l’accès réseau sont disponibles.

## Les limites de cette conception

Ce projet vise une utilisation personnelle avec Audiobookshelf. L’état conservé dans des fichiers est séduisant parce que l’échelle opérationnelle reste petite et que son contenu est transparent. Ce choix deviendrait mauvais avec de nombreux workers, plusieurs utilisateurs ou un système de fichiers partagé à distance. Une file de tâches en base de données, avec des baux et des transitions d’état explicites, serait alors plus facile à raisonner.

Le comportement externe reste la plus grande variable incontrôlée. YouTube modifie ses exigences d’extraction, les cookies expirent, la couverture SponsorBlock varie selon la vidéo et `yt-dlp` évolue assez vite pour que le projet installe une version courante hors du fichier de verrouillage. L’image Docker inclut Deno pour les défis JavaScript actuels de YouTube, mais aucun choix de packaging ne peut stabiliser définitivement un extracteur externe.

La frontière locale, elle, est nette : on ne modifie pas l’état durable parce qu’une commande semble sûre d’elle. On observe l’artefact, on inscrit sa provenance, on le publie, puis seulement on marque le travail comme terminé.
