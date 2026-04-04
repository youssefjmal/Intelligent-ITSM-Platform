Objet : Avancement PFE — Plateforme ITSM Intelligente + Diagrammes d'architecture

Monsieur Ramzi,

J'espère que vous allez bien. Je vous fais un point complet sur l'avancement de mon projet.

Le projet est une plateforme de gestion des tickets IT (ITSM) dotée d'un copilote d'intelligence artificielle, développée durant mon stage chez Teamwill Consulting. Elle automatise la classification des tickets, propose des recommandations de résolution, détecte les problèmes récurrents et surveille les SLA en temps réel.

Stack technique : Python/FastAPI (backend), Next.js/React (frontend), PostgreSQL avec recherche vectorielle (pgvector), Redis (cache), et un LLM via Ollama pour la phase de tests.

Ce qui est fait et fonctionnel :
- Classification automatique des tickets (priorité, catégorie, type) par LLM + recherche sémantique
- Recommandations de résolution basées sur les tickets résolus similaires (RAG)
- Détection automatique des problèmes récurrents (seuil de 5 incidents similaires)
- Surveillance SLA avec alertes proactives avant dépassement
- Chatbot assistant pour les agents
- Journal d'audit de toutes les décisions IA (traçabilité — conformité ISO 42001)
- Cache Redis pour les performances

Points à noter pour la suite :
- Les accès Jira et les données réelles ne m'ont pas encore été transmis par l'entreprise. Je travaille actuellement avec des données de démonstration. Les modèles IA seront reconfigurés une fois les accès disponibles.
- Les notifications par email (SMTP) seront remplacées par Microsoft Teams via OAuth, pour des raisons de sécurité.
- Un tableau de bord de monitoring Grafana + Prometheus est prévu comme dernière étape avant la soutenance.
- La plateforme vise la conformité avec les normes ISO 42001 (gouvernance de l'IA) et ISO 27001 (sécurité de l'information).

Concernant le rapport, j'ai finalisé le premier chapitre (Cadre général du projet) et je vous l'envoie en pièce jointe pour relecture. Les chapitres suivants sont en cours de rédaction.

Je joins également deux diagrammes d'architecture :
- architecture_system — vue globale (frontend, backend, services externes)
- architecture_ai — les 4 pipelines IA (classification, chat/RAG, embeddings, détection de problèmes)

Je reste disponible pour tout retour ou question.

Cordialement,
Youssef Jmel
Licence Génie Logiciel et Systèmes d'Information — FST Monastir
