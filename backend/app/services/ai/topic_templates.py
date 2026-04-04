"""Central registry for topic-specific advice, validation, and fallback templates."""

from __future__ import annotations

from typing import Final

SUPPORTING_CONTEXT_BY_TOPIC: Final[dict[str, dict[str, str]]] = {
    "network_access": {
        "fr": "Confirmez aussi le contexte d'acces distant, de session VPN ou de routage avant de generaliser le correctif.",
        "en": "Also confirm the remote-access, VPN-session, or routing context before rolling the fix out more broadly.",
    },
    "auth_path": {
        "fr": "Confirmez la propagation d'identite, du token ou du certificat autour du correctif principal.",
        "en": "Confirm the surrounding identity, token, or certificate propagation after the primary fix.",
    },
    "payroll_export": {
        "fr": "Validez le flux d'export ou d'import de bout en bout avec un echantillon representatif.",
        "en": "Validate the end-to-end export or import flow with a representative sample.",
    },
    "mail_transport": {
        "fr": "Confirmez aussi le contexte de routage, de distribution ou de destinataires avec un test controle.",
        "en": "Also confirm routing, distribution, or recipient context with a controlled test.",
    },
    "webhook_rotation": {
        "fr": "Confirmez aussi la cadence approuvee, l'equipe responsable et la fenetre de rappel avant de generaliser le workflow.",
        "en": "Also confirm the approved cadence, owning team, and reminder window before rolling the workflow out more broadly.",
    },
    "scheduled_maintenance": {
        "fr": "Confirmez aussi le calendrier approuve, la liste des prerequis et le responsable d'execution avant de cloturer la tache.",
        "en": "Also confirm the approved schedule, prerequisite checklist, and execution owner before closing the task.",
    },
}

GROUNDED_ACTION_TEMPLATES: Final[dict[str, dict[str, list[str]]]] = {
    "crm_integration": {
        "en": [
            "Verify the CRM integration token currently stored after the recent token rotation.",
            "Check the sync worker logs for authentication failures or stale-token reuse before the next retry.",
            "Trigger a controlled CRM sync on one affected record to confirm new updates are processed with the refreshed credential.",
        ],
        "fr": [
            "Verifiez le token d'integration CRM actuellement stocke apres la rotation recente.",
            "Controlez les logs du worker de synchronisation pour des erreurs d'authentification ou une reutilisation d'ancien token avant le prochain retry.",
            "Declenchez une synchronisation CRM controlee sur un element affecte pour confirmer que les nouvelles mises a jour passent avec le credential rafraichi.",
        ],
    },
    "notification_distribution": {
        "en": [
            "Verify the payroll approval notification distribution rule and confirm the expected manager recipient mapping.",
            "Send one controlled approval notice and confirm it reaches the expected manager recipient path.",
        ],
        "fr": [
            "Verifiez la regle de distribution des notifications d'approbation paie et confirmez le mapping attendu des responsables destinataires.",
            "Envoyez un avis d'approbation controle et confirmez qu'il atteint le chemin attendu vers le responsable destinataire.",
        ],
    },
    "payroll_export": {
        "en": [
            "Verify the payroll export formatter and the date-column mapping before the next import.",
            "Generate one control export and compare its date serialization against a known-good file.",
            "Run one import validation with the corrected export to confirm the downstream parser accepts the schema.",
        ],
        "fr": [
            "Verifiez le formateur d'export paie et le mapping des colonnes de date avant le prochain import.",
            "Generez un export de controle et comparez sa serialisation de date avec un fichier valide.",
            "Lancez une validation d'import avec l'export corrige pour confirmer que le parseur aval accepte le schema.",
        ],
    },
    "mail_transport": {
        "en": [
            "Verify the affected relay, connector, or forwarding rule configuration on the current mail path.",
            "Send one controlled test message and confirm it clears the expected queue or routing path.",
        ],
        "fr": [
            "Verifiez la configuration du relay, du connecteur ou de la regle de transfert sur le flux mail concerne.",
            "Envoyez un message de test controle et confirmez qu'il traverse la file ou le routage attendu.",
        ],
    },
    "network_access": {
        "en": [
            "Verify the VPN route, gateway, or policy path that matches the affected access flow.",
            "Retest access from one affected user after the route or policy check to confirm the same path is restored.",
        ],
        "fr": [
            "Verifiez la route VPN, la passerelle ou la politique qui correspond au flux d'acces affecte.",
            "Retestez l'acces depuis un utilisateur affecte apres la verification de route ou de politique pour confirmer que le meme chemin est retabli.",
        ],
    },
    "auth_path": {
        "en": [
            "Verify the relevant authentication token, certificate, or policy state on the affected sign-in path.",
            "Retest one affected sign-in after the policy or certificate check to confirm access is restored.",
        ],
        "fr": [
            "Verifiez l'etat du token, du certificat ou de la politique d'authentification sur le chemin de connexion affecte.",
            "Retestez une connexion affectee apres la verification de la politique ou du certificat pour confirmer que l'acces est retabli.",
        ],
    },
}

GROUNDED_ACTION_REASONS: Final[dict[str, dict[str, list[str]]]] = {
    "crm_integration": {
        "en": [
            "",
            "Recent evidence points to worker-side credential reuse after token rotation.",
            "The incident reports stalled updates, so one controlled sync validates the fix on the affected workflow.",
        ],
        "fr": [
            "",
            "Les preuves recentes pointent vers une reutilisation du credential par le worker apres la rotation du token.",
            "L'incident signale des mises a jour bloquees, donc une synchronisation controlee valide le correctif sur le flux affecte.",
        ],
    },
    "payroll_export": {
        "en": [
            "",
            "The strongest evidence stays in the export/date-format family, so the control sample must confirm the exact serialization path.",
            "A downstream import check confirms the fix on the same schema path that is failing now.",
        ],
        "fr": [
            "",
            "La preuve la plus forte reste dans la famille export/format de date, donc l'echantillon de controle doit confirmer le chemin exact de serialisation.",
            "Une verification d'import aval confirme le correctif sur le meme chemin de schema qui echoue actuellement.",
        ],
    },
}

SERVICE_REQUEST_ACTIONS_BY_TOPIC: Final[dict[str, dict[str, list[str]]]] = {
    "account_provisioning": {
        "en": [
            "Confirm the approved account scope, owning team, and target system before provisioning the identity.",
            "Provision the account or service identity with the approved access scope and credential delivery path.",
            "Record the owner, lifecycle expectations, and completion evidence on the ticket.",
        ],
        "fr": [
            "Confirmez le perimetre de compte approuve, l'equipe responsable et le systeme cible avant de provisionner l'identite.",
            "Provisionnez le compte ou l'identite de service avec le perimetre d'acces approuve et le chemin de remise du credential.",
            "Consignez le responsable, les attentes de cycle de vie et la preuve de completion sur le ticket.",
        ],
    },
    "access_provisioning": {
        "en": [
            "Confirm the approved access scope, target resource, and least-privilege intent before granting access.",
            "Apply the approved group, role, or permission change and document the effective access path.",
            "Notify the requester or owner and capture validation on the ticket.",
        ],
        "fr": [
            "Confirmez le perimetre d'acces approuve, la ressource cible et l'intention de moindre privilege avant d'accorder l'acces.",
            "Appliquez le changement de groupe, role ou permission approuve et documentez le chemin d'acces effectif.",
            "Notifiez le demandeur ou le responsable et consignez la validation sur le ticket.",
        ],
    },
    "credential_rotation": {
        "en": [
            "Confirm the approved rotation window, owning integration, and dependency list before rotating the credential or secret.",
            "Rotate the credential or secret and update the dependent configuration or reminder artifact in the same workflow.",
            "Record the next rotation expectation and the owning team confirmation on the ticket.",
        ],
        "fr": [
            "Confirmez la fenetre de rotation approuvee, l'integration responsable et la liste des dependances avant de faire tourner le credential ou le secret.",
            "Faites tourner le credential ou le secret et mettez a jour la configuration dependante ou l'artefact de rappel dans le meme workflow.",
            "Consignez la prochaine attente de rotation et la confirmation de l'equipe responsable sur le ticket.",
        ],
    },
    "webhook_rotation": {
        "en": [
            "Confirm the approved webhook or secret-rotation cadence and the owning integration before creating or updating the reminder task.",
            "Create or update the reminder task with the expected schedule, owner, and subscriber scope.",
            "Notify the owning team or subscriber group and capture confirmation on the ticket.",
        ],
        "fr": [
            "Confirmez la cadence approuvee de rotation de webhook ou de secret ainsi que l'integration responsable avant de creer ou mettre a jour la tache de rappel.",
            "Creez ou mettez a jour la tache de rappel avec le calendrier attendu, le responsable et le perimetre des abonnes.",
            "Notifiez l'equipe responsable ou le groupe abonne et consignez la confirmation sur le ticket.",
        ],
    },
    "scheduled_maintenance": {
        "en": [
            "Confirm the approved maintenance schedule, execution owner, and prerequisite checklist for the recurring task.",
            "Create or update the recurring maintenance reminder with the expected cadence and execution window.",
            "Notify the responsible team and capture completion expectations on the ticket.",
        ],
        "fr": [
            "Confirmez le calendrier de maintenance approuve, le responsable d'execution et la liste des prerequis pour la tache recurrente.",
            "Creez ou mettez a jour le rappel de maintenance recurrente avec la cadence attendue et la fenetre d'execution.",
            "Notifiez l'equipe responsable et consignez les attentes de cloture sur le ticket.",
        ],
    },
    "notification_distribution_change": {
        "en": [
            "Confirm the intended recipients, trigger scope, and owning team before changing the distribution or forwarding rule.",
            "Apply the approved recipient or forwarding change and document the effective routing rule on the ticket.",
            "Notify stakeholders and capture the verification outcome on the ticket.",
        ],
        "fr": [
            "Confirmez les destinataires attendus, le perimetre de declenchement et l'equipe responsable avant de modifier la regle de distribution ou de transfert.",
            "Appliquez le changement approuve de destinataires ou de transfert et documentez la regle de routage effective sur le ticket.",
            "Notifiez les parties prenantes et consignez le resultat de verification sur le ticket.",
        ],
    },
    "integration_configuration": {
        "en": [
            "Confirm the integration owner, target endpoint, authentication method, and prerequisites before changing configuration.",
            "Apply the approved integration configuration change and record the effective parameters or source-of-truth reference.",
            "Notify the owning team and capture the validation result on the ticket.",
        ],
        "fr": [
            "Confirmez le responsable de l'integration, le point de terminaison cible, la methode d'authentification et les prerequis avant de modifier la configuration.",
            "Appliquez le changement de configuration d'integration approuve et consignez les parametres effectifs ou la reference de source de verite.",
            "Notifiez l'equipe responsable et consignez le resultat de validation sur le ticket.",
        ],
    },
    "device_provisioning": {
        "en": [
            "Confirm the approved device scope, recipient, delivery timing, and prerequisite checklist before provisioning the equipment.",
            "Prepare or provision the requested device profile, accessory set, or field-connectivity package using the documented workflow.",
            "Record the owner, delivery state, and validation evidence on the ticket.",
        ],
        "fr": [
            "Confirmez le perimetre d'equipement approuve, le beneficiaire, le calendrier de remise et la liste des prerequis avant de provisionner le materiel.",
            "Preparez ou provisionnez le profil d'equipement, le jeu d'accessoires ou le package de connectivite terrain demande selon le workflow documente.",
            "Consignez le responsable, l'etat de remise et la preuve de validation sur le ticket.",
        ],
    },
    "reporting_workspace_setup": {
        "en": [
            "Confirm the intended dashboard or reporting workspace scope, audience, and approval context before building the workspace.",
            "Create or update the requested dashboard, widgets, or review board using the documented reporting workflow.",
            "Share the workspace with the intended audience and record the validation outcome on the ticket.",
        ],
        "fr": [
            "Confirmez le perimetre attendu du tableau de bord ou de l'espace de reporting, l'audience et le contexte d'approbation avant de construire l'espace.",
            "Creez ou mettez a jour le tableau de bord, les widgets ou le tableau de revue demandes selon le workflow de reporting documente.",
            "Partagez l'espace avec l'audience attendue et consignez le resultat de validation sur le ticket.",
        ],
    },
}

SERVICE_REQUEST_VALIDATION_BY_TOPIC: Final[dict[str, dict[str, str]]] = {
    "account_provisioning": {
        "fr": "Verifiez que le compte cible existe, que le proprietaire attendu est renseigne et que le perimetre d'acces approuve est applique.",
        "en": "Verify that the target account exists, the expected owner is recorded, and the approved access scope is applied.",
    },
    "access_provisioning": {
        "fr": "Verifiez que le demandeur atteint bien la ressource cible sans obtenir d'autorisation plus large que prevu.",
        "en": "Verify that the requester reaches the intended resource without receiving broader access than approved.",
    },
    "credential_rotation": {
        "fr": "Verifiez que le credential tourne est present dans le systeme cible et que l'equipe responsable confirme le nouveau cycle de vie.",
        "en": "Verify that the rotated credential is present in the target system and the owning team confirms the updated lifecycle.",
    },
    "webhook_rotation": {
        "fr": "Verifiez que le rappel, la cadence et les destinataires attendus sont visibles sur la tache ou l'abonnement associe.",
        "en": "Verify that the reminder, cadence, and expected recipients are visible on the task or related subscription.",
    },
    "scheduled_maintenance": {
        "fr": "Verifiez que la tache recurrente apparait sur la bonne fenetre de maintenance avec le responsable attendu.",
        "en": "Verify that the recurring task appears in the correct maintenance window with the expected owner.",
    },
    "notification_distribution_change": {
        "fr": "Envoyez un test controle et confirmez que seuls les destinataires approuves recoivent la notification ou le transfert.",
        "en": "Send a controlled test and confirm that only the approved recipients receive the notification or forwarding change.",
    },
    "integration_configuration": {
        "fr": "Verifiez que l'integration atteint bien le point de terminaison attendu avec la configuration approuvee.",
        "en": "Verify that the integration reaches the expected endpoint with the approved configuration.",
    },
    "device_provisioning": {
        "fr": "Verifiez que l'equipement, le profil ou l'accessoire demandes sont prepares pour le bon destinataire avec l'etat attendu.",
        "en": "Verify that the requested device, profile, or accessory is prepared for the correct recipient with the expected status.",
    },
    "reporting_workspace_setup": {
        "fr": "Verifiez que le tableau de bord ou l'espace de reporting est visible par l'audience attendue avec les widgets ou vues demandes.",
        "en": "Verify that the dashboard or reporting workspace is visible to the intended audience with the requested widgets or views.",
    },
}
SERVICE_REQUEST_TOPICS: Final[frozenset[str]] = frozenset(
    set(SERVICE_REQUEST_ACTIONS_BY_TOPIC).union(SERVICE_REQUEST_VALIDATION_BY_TOPIC)
)

VALIDATION_STEP_BY_TOPIC: Final[dict[str, dict[str, str]]] = {
    "crm_integration": {
        "fr": "Retestez le service d'integration avec un element affecte et confirmez que le worker recharge bien le credential ou token attendu.",
        "en": "Retest the integration on an affected record and confirm the worker reloaded the expected credential or token.",
    },
    "notification_distribution": {
        "fr": "Envoyez un avis d'approbation controle et confirmez qu'il atteint le responsable destinataire attendu.",
        "en": "Send one controlled approval notice and confirm it reaches the expected manager recipient.",
    },
    "payroll_export": {
        "fr": "Generez un export de controle et validez les champs corriges avant cloture.",
        "en": "Generate a control export and validate the corrected fields before closure.",
    },
    "mail_transport": {
        "fr": "Envoyez un test controle et confirmez que le routage ou le transfert est retabli.",
        "en": "Send a controlled test and confirm routing or forwarding is restored.",
    },
    "network_access": {
        "fr": "Retestez la connectivite ou la connexion avec un utilisateur distant affecte.",
        "en": "Retest connectivity or sign-in with an affected remote user.",
    },
    "auth_path": {
        "fr": "Retestez l'acces ou la connexion pour un utilisateur affecte et confirmez l'etat de la politique.",
        "en": "Retest access or sign-in for an affected user and confirm the policy state.",
    },
}

VALIDATION_ACTIONS_BY_TOPIC: Final[dict[str, dict[str, list[str]]]] = {
    "crm_integration": {
        "en": [
            "Trigger one controlled CRM sync on an affected record and confirm the worker no longer logs authentication or stale-token failures.",
            "Confirm the latest contact update is written with the refreshed integration credential.",
        ],
        "fr": [
            "Declenchez une synchronisation CRM controlee sur un element affecte et confirmez que le worker ne journalise plus d'erreurs d'authentification ou d'ancien token.",
            "Confirmez que la derniere mise a jour de contact est ecrite avec le credential d'integration rafraichi.",
        ],
    },
    "notification_distribution": {
        "en": [
            "Send one controlled approval notice and confirm it reaches the expected manager recipient.",
        ],
        "fr": [
            "Envoyez un avis d'approbation controle et confirmez qu'il atteint le responsable destinataire attendu.",
        ],
    },
    "payroll_export": {
        "en": [
            "Generate one control export and validate the corrected date columns in the downstream import.",
            "Confirm the parser accepts the corrected export schema without shifting date fields.",
        ],
        "fr": [
            "Generez un export de controle et validez les colonnes de date corrigees dans l'import aval.",
            "Confirmez que le parseur accepte le schema d'export corrige sans deplacer les champs de date.",
        ],
    },
    "mail_transport": {
        "en": [
            "Send one controlled test message and confirm the expected relay or connector path is restored.",
        ],
        "fr": [
            "Envoyez un message de test controle et confirmez que le chemin relay ou connecteur attendu est retabli.",
        ],
    },
    "network_access": {
        "en": [
            "Retest access from one affected user and confirm the same route or policy path stays stable.",
        ],
        "fr": [
            "Retestez l'acces depuis un utilisateur affecte et confirmez que le meme chemin de route ou de politique reste stable.",
        ],
    },
}

SAFE_DIAGNOSTIC_ACTION_BY_TOPIC: Final[dict[str, dict[str, str]]] = {
    "payroll_export": {
        "fr": "Verifiez le formatteur d'export, comparez les colonnes de dates avec un export valide, puis confirmez le mapping attendu avant nouvel import.",
        "en": "Verify the export formatter, compare the date columns against a known-good export, and confirm the expected mapping before re-import.",
    },
    "notification_distribution": {
        "fr": "Verifiez la regle de distribution des notifications d'approbation paie et confirmez le mapping attendu des responsables destinataires.",
        "en": "Verify the payroll approval notification distribution rule and confirm the expected manager recipient mapping.",
    },
    "crm_integration": {
        "fr": "Verifiez que le credential ou token d'integration tourne est valide, confirmez que le worker de synchronisation a recharge la nouvelle valeur, puis inspectez les journaux du worker pour une erreur d'authentification ou de reprise.",
        "en": "Verify the rotated integration credential or token is valid, confirm the sync worker reloaded the new value, and inspect the worker logs for authentication or retry failures.",
    },
    "mail_transport": {
        "fr": "Verifiez la regle de distribution ou le mapping des destinataires, puis confirmez le routage attendu avec un test controle.",
        "en": "Verify the distribution rule or recipient mapping, then confirm the expected routing with a controlled test.",
    },
    "network_access": {
        "fr": "Verifiez la configuration de session ou de routage VPN et retestez l'acces avec un utilisateur affecte.",
        "en": "Verify the VPN session or routing configuration and retest access with an affected user.",
    },
    "auth_path": {
        "fr": "Verifiez l'etat du token, du certificat ou de la politique d'authentification sur le chemin de connexion affecte.",
        "en": "Verify the relevant authentication token, certificate, or policy state on the affected sign-in path.",
    },
}


def topic_supporting_context(topic: str | None, *, lang: str) -> str | None:
    normalized = str(topic or "").strip().lower()
    return SUPPORTING_CONTEXT_BY_TOPIC.get(normalized, {}).get(lang)


def topic_grounded_action_templates(topic: str | None, *, lang: str) -> list[str]:
    normalized = str(topic or "").strip().lower()
    return list(GROUNDED_ACTION_TEMPLATES.get(normalized, {}).get(lang, []))


def topic_grounded_action_reasons(topic: str | None, *, lang: str) -> list[str]:
    normalized = str(topic or "").strip().lower()
    return list(GROUNDED_ACTION_REASONS.get(normalized, {}).get(lang, []))


def topic_validation_step(topic: str | None, *, lang: str) -> str | None:
    normalized = str(topic or "").strip().lower()
    return VALIDATION_STEP_BY_TOPIC.get(normalized, {}).get(lang)


def topic_validation_actions(topic: str | None, *, lang: str) -> list[str]:
    normalized = str(topic or "").strip().lower()
    return list(VALIDATION_ACTIONS_BY_TOPIC.get(normalized, {}).get(lang, []))


def topic_safe_diagnostic_action(topic: str | None, *, lang: str) -> str | None:
    normalized = str(topic or "").strip().lower()
    return SAFE_DIAGNOSTIC_ACTION_BY_TOPIC.get(normalized, {}).get(lang)


def topic_service_request_actions(topic: str | None, *, lang: str) -> list[str]:
    normalized = str(topic or "").strip().lower()
    return list(SERVICE_REQUEST_ACTIONS_BY_TOPIC.get(normalized, {}).get(lang, []))


def topic_service_request_validation(topic: str | None, *, lang: str) -> str | None:
    normalized = str(topic or "").strip().lower()
    return SERVICE_REQUEST_VALIDATION_BY_TOPIC.get(normalized, {}).get(lang)


def service_request_topics() -> frozenset[str]:
    return SERVICE_REQUEST_TOPICS
