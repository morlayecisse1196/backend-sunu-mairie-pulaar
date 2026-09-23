# Migrations à appliquer — backend v3

Les migrations **011 à 016 ne sont PAS appliquées** sur la base Supabase à la
date d'écriture. Le code fonctionne sans elles, mais en mode dégradé **explicite** :
il renvoie `503 {"code": "migration_manquante", "migration": "0XX"}` ou bascule en
mode mémoire — jamais de crash, jamais de donnée inventée.

Appliquer dans l'ordre : chaque fichier est idempotent (`if not exists`,
`create or replace`), donc rejouable sans risque.

---

## Comment appliquer

**Supabase Studio** → SQL Editor → coller le contenu du fichier → Run.
Ou en ligne de commande :

```bash
psql "$DATABASE_URL" -f migrations/011_securite_profils.sql
```

> Appliquer d'abord sur un projet de test si un pilote tourne déjà : la 011
> restreint des écritures que l'application mobile actuelle effectuait
> directement (voir ci-dessous).

---

## Ordre et contenu

### 011 — `011_securite_profils.sql` · **sécurité, prioritaire**

RLS sur `profiles` + trigger `proteger_profil()` : hors `service_role`, le rôle
n'est plus modifiable, et la commune d'un agent non plus.

⚠️ **Effet de bord voulu** : l'application mobile ne peut plus écrire `profiles`
elle-même. Elle doit passer par `POST /me/profil-citoyen` (déjà en place côté
backend). Vérifier que la version mobile déployée utilise bien cet endpoint
**avant** d'appliquer cette migration en production.

```sql
-- vérification
select tablename, rowsecurity from pg_tables where tablename = 'profiles';
select tgname from pg_trigger where tgrelid = 'public.profiles'::regclass;
```

### 012 — `012_web_v3_historique.sql` · **web consultant/admin**

- `profiles` : `nom_complet`, `telephone`, `fonction`, `langue_preferee`,
  `preferences` (jsonb), `doit_changer_mot_de_passe`, `derniere_connexion_vue`
- `dossiers.motif_blocage`
- `templates.actif`, `templates.mis_a_jour_le`
- tables `notes_internes` et `dossier_evenements`
- trigger `proteger_profil()` étendu à `doit_changer_mot_de_passe`

Sans elle : `GET …/notes` et `…/historique` renvoient 503 `migration_manquante`,
`PATCH /me` retombe sur `user_metadata`, et les transitions de statut rejouent
l'écriture sans `motif_blocage`.

```sql
select column_name from information_schema.columns
 where table_name = 'profiles' and column_name in
   ('nom_complet','telephone','fonction','preferences','doit_changer_mot_de_passe','derniere_connexion_vue');
select to_regclass('public.notes_internes'), to_regclass('public.dossier_evenements');
```

### 013 — `013_dialogue_sessions.sql` · **temps réel mobile, prioritaire**

État du dialogue persisté : propriété par citoyen, statut `active`/`close`,
index **unique partiel** sur la clé client d'une session active.

Sans elle : le dialogue fonctionne mais **en mémoire seule** — un redémarrage du
serveur perd les dialogues en cours (comportement actuel, signalé dans les logs).

```sql
select to_regclass('public.dialogue_sessions');
select indexname from pg_indexes where tablename = 'dialogue_sessions';
```

### 014 — `014_notifications_appareils.sql`

`notifications` (fil du citoyen et des agents) et `appareils` (jetons FCM).
Sans elle : les endpoints `/notifications` et `/me/appareils` renvoient 503 ;
les transitions de statut continuent de fonctionner.

```sql
select to_regclass('public.notifications'), to_regclass('public.appareils');
```

### 015 — `015_communes_coordonnees.sql`

`communes.latitude` / `longitude`, pour `GET /communes/proche`.

**Les coordonnées elles-mêmes ne sont pas dans la migration** : elles doivent
être renseignées commune par commune, à partir d'une source vérifiable — un
`update` de coordonnées inventées produirait une mauvaise commune pour un
citoyen qui ne sait pas lire la liste. Un exemple est laissé en commentaire.

```sql
select nom, latitude, longitude from public.communes order by nom;
```

### 016 — `016_journal_audit.sql`

`journal_audit` : traçabilité des actions sensibles (comptes, communes, tampons,
modèles, déblocages, documents). Table en **ajout seul** — `update` et `delete`
révoqués pour `anon` et `authenticated`.

Sans elle : l'audit est silencieusement ignoré (une écriture d'audit ne doit
jamais faire échouer l'action métier), `GET /admin/journal` renvoie 503 et
`GET /me/activite` renvoie une liste vide.

```sql
select to_regclass('public.journal_audit');
select privilege_type from information_schema.role_table_grants
 where table_name = 'journal_audit' and grantee = 'authenticated';
```

---

## Vérification d'ensemble

```sql
select to_regclass('public.dialogue_sessions')  as m013,
       to_regclass('public.notes_internes')     as m012a,
       to_regclass('public.dossier_evenements') as m012b,
       to_regclass('public.notifications')      as m014a,
       to_regclass('public.appareils')          as m014b,
       to_regclass('public.journal_audit')      as m016;
```

Toutes les lignes non nulles ⇒ le backend v3 tourne sans dégradation.

Côté application, après application : `GET /admin/journal` doit répondre 200
(liste vide), `GET /consultant/dossiers/{id}/historique` doit répondre 200, et
les journaux du serveur ne doivent plus contenir « migration … absente ».
