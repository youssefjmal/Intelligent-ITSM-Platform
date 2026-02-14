"use client"

import React, { createContext, useContext, useState, useCallback } from "react"

export type Locale = "fr" | "en"

const translations = {
  // Nav & Layout
  "nav.dashboard": { fr: "Tableau de Bord", en: "Dashboard" },
  "nav.tickets": { fr: "Tickets", en: "Tickets" },
  "nav.newTicket": { fr: "Nouveau Ticket", en: "New Ticket" },
  "nav.chat": { fr: "Assistant IA", en: "AI Assistant" },
  "nav.recommendations": { fr: "Recommandations", en: "Recommendations" },
  "nav.problems": { fr: "Problemes", en: "Problems" },
  "nav.settings": { fr: "Parametres", en: "Settings" },
  "nav.collapse": { fr: "Reduire", en: "Collapse" },
  "nav.admin": { fr: "Administration", en: "Administration" },

  // App shell
  "app.title": { fr: "Teamwil Ticket Manager", en: "Teamwil Ticket Manager" },
  "app.user": { fr: "Utilisateur", en: "User" },
  "app.logout": { fr: "Deconnexion", en: "Logout" },
  "app.notifications": { fr: "Notifications", en: "Notifications" },

  // Dashboard
  "dashboard.title": { fr: "Tableau de Bord", en: "Dashboard" },
  "dashboard.subtitle": { fr: "Vue d'ensemble de l'activite des tickets Teamwil Consulting", en: "Overview of Teamwil Consulting ticket activity" },
  "dashboard.problemInsightsTitle": { fr: "Insights Problemes", en: "Problem Insights" },
  "dashboard.problemInsightsSubtitle": { fr: "Incidents repetitifs detectes avec acces direct aux details.", en: "Detected repetitive incidents with direct access to details." },
  "dashboard.problemNoData": { fr: "Aucun incident repetitif detecte pour le moment.", en: "No repetitive incidents detected yet." },
  "dashboard.problemBrief": { fr: "{occurrences} occurrences similaires, {active} actives, priorite max {priority}.", en: "{occurrences} similar occurrences, {active} active, highest priority {priority}." },
  "dashboard.criticalRecentTitle": { fr: "Tickets critiques recents", en: "Recent critical tickets" },
  "dashboard.criticalRecentSubtitle": { fr: "Tickets critiques actifs crees sur les {days} derniers jours.", en: "Active critical tickets created in the last {days} days." },
  "dashboard.criticalRecentEmpty": { fr: "Aucun ticket critique recent a traiter.", en: "No recent critical tickets to handle." },
  "dashboard.viewCriticalTickets": { fr: "Voir les tickets critiques", en: "View critical tickets" },
  "dashboard.viewProblemTickets": { fr: "Voir problemes", en: "View problems" },
  "dashboard.viewStaleTickets": { fr: "Voir les tickets sans suivi", en: "View long-untreated tickets" },
  "dashboard.staleTicketsTitle": { fr: "Tickets sans suivi recent", en: "Long-untreated tickets" },
  "dashboard.staleTicketsSubtitle": { fr: "Tickets actifs sans mise a jour depuis au moins {days} jours.", en: "Active tickets with no update for at least {days} days." },
  "dashboard.staleTicketsEmpty": { fr: "Aucun ticket actif stale detecte.", en: "No stale active tickets detected." },
  "dashboard.ticketAgeDays": { fr: "Age: {days} j", en: "Age: {days} d" },
  "dashboard.lastUpdateDays": { fr: "Derniere mise a jour: {days} j", en: "Last update: {days} d" },
  "dashboard.problemOccurrences": { fr: "Occurrences", en: "Occurrences" },
  "dashboard.problemActive": { fr: "Actifs", en: "Active" },
  "dashboard.problemPromoted": { fr: "Promus Problem", en: "Promoted to Problem" },
  "dashboard.problemPatterns": { fr: "patterns detectes", en: "patterns detected" },
  "dashboard.problemLastOccurrence": { fr: "Derniere occurrence", en: "Last occurrence" },
  "dashboard.problemTickets": { fr: "Tickets associes", en: "Linked tickets" },
  "dashboard.problemViewLatest": { fr: "Voir dernier", en: "View latest" },
  "dashboard.problemTrigger": { fr: "Declencheur Problem", en: "Problem trigger" },
  "dashboard.problemTriggered": { fr: "Trigger actif", en: "Trigger active" },
  "dashboard.problemWatching": { fr: "Sous surveillance", en: "Monitoring" },
  "dashboard.problemTrigger5in7": { fr: "5 incidents similaires sur 7 jours", en: "5 similar incidents in 7 days" },
  "dashboard.problemTrigger4sameDay": { fr: "4 incidents similaires le meme jour", en: "4 similar incidents on the same day" },
  "dashboard.problemTriggerSummary": { fr: "{count7d} incidents/7j, pic journalier {count1d}.", en: "{count7d} incidents/7d, daily peak {count1d}." },
  "dashboard.problemTriggerNotReached": { fr: "Seuil non atteint ({count7d}/7j, pic {count1d}/jour).", en: "Threshold not reached ({count7d}/7d, peak {count1d}/day)." },
  "dashboard.problemRecommendation": { fr: "Recommendation IA", en: "AI recommendation" },
  "kpi.totalTickets": { fr: "Total Tickets", en: "Total Tickets" },
  "kpi.inProgress": { fr: "En Cours", en: "In Progress" },
  "kpi.resolvedClosed": { fr: "Resolus / Fermes", en: "Resolved / Closed" },
  "kpi.critical": { fr: "Critiques", en: "Critical" },
  "kpi.avgTime": { fr: "Temps Moyen", en: "Avg. Time" },
  "kpi.resolutionRate": { fr: "Taux de Resolution", en: "Resolution Rate" },
  "kpi.opened": { fr: "ouverts", en: "open" },
  "kpi.pendingDesc": { fr: "en attente", en: "pending" },
  "kpi.rateDesc": { fr: "Taux", en: "Rate" },
  "kpi.maxPriority": { fr: "Priorite maximale", en: "Maximum priority" },
  "kpi.resolutionTime": { fr: "Temps de resolution", en: "Resolution time" },
  "kpi.thisMonth": { fr: "Ce mois-ci", en: "This month" },

  // Charts
  "chart.trends": { fr: "Tendance des Tickets (6 semaines)", en: "Ticket Trends (6 weeks)" },
  "chart.priorityDist": { fr: "Repartition par Priorite", en: "Priority Distribution" },
  "chart.categoryBreak": { fr: "Tickets par Categorie", en: "Tickets by Category" },
  "chart.opened": { fr: "Ouverts", en: "Opened" },
  "chart.closed": { fr: "Fermes", en: "Closed" },
  "chart.pending": { fr: "En attente", en: "Pending" },

  // Recent Activity
  "activity.title": { fr: "Activite Recente", en: "Recent Activity" },
  "activity.justNow": { fr: "A l'instant", en: "Just now" },
  "activity.hoursAgo": { fr: "il y a {n}h", en: "{n}h ago" },
  "activity.daysAgo": { fr: "il y a {n}j", en: "{n}d ago" },

  // Tickets
  "tickets.title": { fr: "Tickets", en: "Tickets" },
  "tickets.subtitle": { fr: "Gerez et suivez tous vos tickets", en: "Manage and track all your tickets" },
  "tickets.new": { fr: "Nouveau Ticket", en: "New Ticket" },
  "tickets.search": { fr: "Rechercher par titre, ID ou assignee...", en: "Search by title, ID or assignee..." },
  "tickets.allStatuses": { fr: "Tous les statuts", en: "All statuses" },
  "tickets.allPriorities": { fr: "Toutes les priorites", en: "All priorities" },
  "tickets.allCategories": { fr: "Toutes les categories", en: "All categories" },
  "tickets.status": { fr: "Statut", en: "Status" },
  "tickets.priority": { fr: "Priorite", en: "Priority" },
  "tickets.category": { fr: "Categorie", en: "Category" },
  "tickets.assignee": { fr: "Assigne", en: "Assignee" },
  "tickets.date": { fr: "Date", en: "Date" },
  "tickets.id": { fr: "ID", en: "ID" },
  "tickets.titleCol": { fr: "Titre", en: "Title" },
  "tickets.noResults": { fr: "Aucun ticket trouve", en: "No tickets found" },
  "tickets.shown": { fr: "ticket(s) affiche(s)", en: "ticket(s) shown" },
  "tickets.view": { fr: "Voir le ticket", en: "View ticket" },
  "tickets.resolvedOrClosed": { fr: "Resolus / Fermes", en: "Resolved / Closed" },
  "tickets.focusTotal": { fr: "Detail: tous les tickets", en: "Focus: all tickets" },
  "tickets.focusInProgress": { fr: "Detail: tickets en cours", en: "Focus: in-progress tickets" },
  "tickets.focusResolved": { fr: "Detail: tickets resolus/fermes", en: "Focus: resolved/closed tickets" },
  "tickets.focusCritical": { fr: "Detail: tickets critiques", en: "Focus: critical tickets" },
  "tickets.focusProblem": { fr: "Detail: incidents Problem detectes", en: "Focus: detected problem incidents" },
  "tickets.focusStale": { fr: "Detail: tickets sans suivi recent", en: "Focus: long-untreated tickets" },
  "tickets.focusAvgTime": { fr: "Detail: tickets resolus (temps moyen)", en: "Focus: resolved tickets (avg time)" },
  "tickets.focusResolutionRate": { fr: "Detail: tickets resolus (taux de resolution)", en: "Focus: resolved tickets (resolution rate)" },

  // New Ticket
  "newTicket.title": { fr: "Nouveau Ticket", en: "New Ticket" },
  "newTicket.subtitle": { fr: "Creez un nouveau ticket avec assistance IA pour la classification et les recommandations", en: "Create a new ticket with AI assistance for classification and recommendations" },
  "form.details": { fr: "Details du Ticket", en: "Ticket Details" },
  "form.title": { fr: "Titre", en: "Title" },
  "form.titlePlaceholder": { fr: "Decrivez brievement le probleme ou la demande...", en: "Briefly describe the issue or request..." },
  "form.description": { fr: "Description", en: "Description" },
  "form.descPlaceholder": { fr: "Fournissez une description detaillee incluant les etapes de reproduction, l'impact, et le comportement attendu...", en: "Provide a detailed description including reproduction steps, impact, and expected behavior..." },
  "form.aiClassify": { fr: "Classification IA", en: "AI Classification" },
  "form.aiClassifyDesc": { fr: "L'IA analysera le contenu pour suggerer la priorite et la categorie", en: "AI will analyze the content to suggest priority and category" },
  "form.priority": { fr: "Priorite", en: "Priority" },
  "form.category": { fr: "Categorie", en: "Category" },
  "form.assignTo": { fr: "Assigner a", en: "Assign to" },
  "form.assignPlaceholder": { fr: "Selectionner un membre...", en: "Select a member..." },
  "form.assigneeManualPlaceholder": { fr: "Saisir un assignee...", en: "Enter an assignee..." },
  "form.autoAssign": { fr: "Auto-assignation", en: "Auto-assign" },
  "form.tags": { fr: "Tags", en: "Tags" },
  "form.addTag": { fr: "Ajouter un tag...", en: "Add a tag..." },
  "form.add": { fr: "Ajouter", en: "Add" },
  "form.cancel": { fr: "Annuler", en: "Cancel" },
  "form.create": { fr: "Creer le Ticket", en: "Create Ticket" },
  "form.aiSuggestions": { fr: "Suggestions IA", en: "AI Suggestions" },
  "form.suggestedPriority": { fr: "Priorite suggeree", en: "Suggested priority" },
  "form.suggestedCategory": { fr: "Categorie suggeree", en: "Suggested category" },
  "form.suggestedAssignee": { fr: "Assigne suggere", en: "Suggested assignee" },
  "form.recommendedSolutions": { fr: "Solutions recommandees", en: "Recommended solutions" },
  "form.aiHelp": { fr: "Aide IA", en: "AI Help" },
  "form.aiHelpDesc": { fr: "Remplissez le titre et la description, puis cliquez sur \"Classification IA\" pour obtenir des suggestions automatiques de priorite, categorie, et des recommandations basees sur les tickets precedents.", en: "Fill in the title and description, then click \"AI Classification\" to get automatic suggestions for priority, category, and recommendations based on previous tickets." },

  // Priority / Status / Category labels
  "priority.critical": { fr: "Critique", en: "Critical" },
  "priority.high": { fr: "Haute", en: "High" },
  "priority.medium": { fr: "Moyenne", en: "Medium" },
  "priority.low": { fr: "Basse", en: "Low" },
  "status.open": { fr: "Ouvert", en: "Open" },
  "status.inProgress": { fr: "En cours", en: "In Progress" },
  "status.pending": { fr: "En attente", en: "Pending" },
  "status.resolved": { fr: "Resolu", en: "Resolved" },
  "status.closed": { fr: "Ferme", en: "Closed" },
  "category.bug": { fr: "Bug", en: "Bug" },
  "category.feature": { fr: "Fonctionnalite", en: "Feature" },
  "category.support": { fr: "Support", en: "Support" },
  "category.infrastructure": { fr: "Infrastructure", en: "Infrastructure" },
  "category.network": { fr: "Reseau", en: "Network" },
  "category.security": { fr: "Securite", en: "Security" },
  "category.application": { fr: "Application", en: "Application" },
  "category.service_request": { fr: "Demande de service", en: "Service Request" },
  "category.hardware": { fr: "Materiel", en: "Hardware" },
  "category.email": { fr: "Email", en: "Email" },
  "category.problem": { fr: "Probleme", en: "Problem" },

  // Ticket Detail
  "detail.back": { fr: "Retour", en: "Back" },
  "detail.reportedBy": { fr: "Signale par", en: "Reported by" },
  "detail.on": { fr: "le", en: "on" },
  "detail.description": { fr: "Description", en: "Description" },
  "detail.resolution": { fr: "Resolution", en: "Resolution" },
  "detail.comments": { fr: "Commentaires", en: "Comments" },
  "detail.noComments": { fr: "Aucun commentaire", en: "No comments" },
  "detail.info": { fr: "Informations", en: "Information" },
  "detail.assignedTo": { fr: "Assigne a", en: "Assigned to" },
  "detail.createdAt": { fr: "Cree le", en: "Created on" },
  "detail.updatedAt": { fr: "Mis a jour", en: "Updated" },
  "detail.aiRecommendations": { fr: "Recommandations IA", en: "AI recommendations" },
  "detail.aiRecommendationsDesc": { fr: "Suggestions generees automatiquement a l'ouverture de ce ticket.", en: "Suggestions generated automatically when opening this ticket." },
  "detail.aiRecommendationsLoading": { fr: "Generation des recommandations IA...", en: "Generating AI recommendations..." },
  "detail.aiRecommendationsError": { fr: "Impossible de charger les recommandations IA.", en: "Could not load AI recommendations." },
  "detail.aiRecommendationsEmpty": { fr: "Aucune recommandation specifique disponible.", en: "No specific recommendation available." },
  "detail.aiSuggestedPriority": { fr: "Priorite suggeree", en: "Suggested priority" },
  "detail.aiSuggestedCategory": { fr: "Categorie suggeree", en: "Suggested category" },
  "detail.aiSuggestedAssignee": { fr: "Assigne suggere", en: "Suggested assignee" },
  "detail.aiRefresh": { fr: "Rafraichir IA", en: "Refresh AI" },
  "detail.notFound": { fr: "Ticket non trouve", en: "Ticket not found" },
  "detail.notFoundDesc": {
    fr: "Le ticket {id} n'existe pas ou a ete supprime.",
    en: "Ticket {id} does not exist or has been deleted.",
  },

  // Chat
  "chat.title": { fr: "Assistant IA - Teamwil", en: "AI Assistant - Teamwil" },
  "chat.subtitle": { fr: "Posez vos questions sur les tickets, obtenez des recommandations et des analyses en temps reel.", en: "Ask questions about tickets, get recommendations and real-time analysis." },
  "chat.howHelp": { fr: "Comment puis-je vous aider ?", en: "How can I help you?" },
  "chat.helpDesc": { fr: "Je peux analyser vos tickets, recommander des solutions et vous aider a prioriser votre travail.", en: "I can analyze your tickets, recommend solutions and help you prioritize your work." },
  "chat.placeholder": { fr: "Posez une question sur vos tickets...", en: "Ask a question about your tickets..." },
  "chat.reset": { fr: "Reinitialiser", en: "Reset" },
  "chat.send": { fr: "Envoyer", en: "Send" },
  "chat.prompt1": { fr: "Quels sont les tickets critiques en cours ?", en: "What are the current critical tickets?" },
  "chat.prompt2": { fr: "Resume l'activite de la semaine", en: "Summarize the week's activity" },
  "chat.prompt3": { fr: "Quels tickets sont en attente depuis longtemps ?", en: "Which tickets have been pending for a long time?" },
  "chat.prompt4": { fr: "Recommande des solutions pour les bugs recurrents", en: "Recommend solutions for recurring bugs" },
  "chat.ticketDraft": { fr: "Brouillon de ticket", en: "Ticket draft" },
  "chat.createTicket": { fr: "Creer le ticket", en: "Create ticket" },
  "chat.ticketCreated": { fr: "Ticket cree:", en: "Ticket created:" },
  "chat.ticketCreateError": { fr: "Impossible de creer le ticket.", en: "Could not create the ticket." },
  "chat.ticketTitle": { fr: "Titre", en: "Title" },
  "chat.ticketDescription": { fr: "Description", en: "Description" },
  "chat.ticketPriority": { fr: "Priorite", en: "Priority" },
  "chat.ticketCategory": { fr: "Categorie", en: "Category" },
  "chat.ticketAssignee": { fr: "Assigne", en: "Assignee" },
  "chat.ticketTags": { fr: "Tags", en: "Tags" },
  "chat.errorReply": { fr: "Une erreur est survenue.", en: "Something went wrong." },

  // Recommendations
  "recs.title": { fr: "Recommandations IA", en: "AI Recommendations" },
  "recs.subtitle": { fr: "Analyses et suggestions generees par l'intelligence artificielle basees sur l'historique des tickets", en: "AI-generated analyses and suggestions based on ticket history" },
  "recs.recommendations": { fr: "Recommandations", en: "Recommendations" },
  "recs.generated": { fr: "Generees par l'IA", en: "AI-generated" },
  "recs.avgConfidence": { fr: "Confiance Moyenne", en: "Average Confidence" },
  "recs.accuracy": { fr: "Taux de precision", en: "Accuracy rate" },
  "recs.highImpact": { fr: "Impact Eleve", en: "High Impact" },
  "recs.treatFirst": { fr: "A traiter en priorite", en: "Priority treatment" },
  "recs.patternsDetected": { fr: "Patterns Detectes", en: "Patterns Detected" },
  "recs.all": { fr: "Tout", en: "All" },
  "recs.patterns": { fr: "Patterns", en: "Patterns" },
  "recs.priorities": { fr: "Priorites", en: "Priorities" },
  "recs.solutions": { fr: "Solutions", en: "Solutions" },
  "recs.workflows": { fr: "Workflows", en: "Workflows" },
  "recs.refresh": { fr: "Actualiser", en: "Refresh" },
  "recs.relatedTickets": { fr: "Tickets lies", en: "Related tickets" },
  "recs.confidence": { fr: "Confiance", en: "Confidence" },
  "recs.pattern": { fr: "Pattern", en: "Pattern" },
  "recs.priority": { fr: "Priorite", en: "Priority" },
  "recs.solution": { fr: "Solution", en: "Solution" },
  "recs.workflow": { fr: "Workflow", en: "Workflow" },
  "recs.impactHigh": { fr: "Impact Eleve", en: "High Impact" },
  "recs.impactMedium": { fr: "Impact Moyen", en: "Medium Impact" },
  "recs.impactLow": { fr: "Impact Faible", en: "Low Impact" },

  // Auth
  "auth.signIn": { fr: "Connexion", en: "Sign In" },
  "auth.signUp": { fr: "Inscription", en: "Sign Up" },
  "auth.createAccount": { fr: "Creer un compte", en: "Create Account" },
  "auth.email": { fr: "Adresse email", en: "Email address" },
  "auth.password": { fr: "Mot de passe", en: "Password" },
  "auth.confirmPassword": { fr: "Confirmer le mot de passe", en: "Confirm password" },
  "auth.fullName": { fr: "Nom complet", en: "Full name" },
  "auth.specializations": { fr: "Specialisations", en: "Specializations" },
  "auth.specializationsPlaceholder": { fr: "Selectionner des specialisations...", en: "Select specializations..." },
  "auth.specializationsSearch": { fr: "Rechercher une specialisation...", en: "Search specializations..." },
  "auth.specializationsEmpty": { fr: "Aucun resultat.", en: "No results found." },
  "auth.namePlaceholder": { fr: "Jean Dupont", en: "John Doe" },
  "auth.emailPlaceholder": { fr: "prenom.nom@exemple.com", en: "name@example.com" },
  "auth.passwordPlaceholder": { fr: "******", en: "******" },
  "auth.confirmPasswordPlaceholder": { fr: "******", en: "******" },
  "auth.role": { fr: "Role", en: "Role" },
  "auth.signInBtn": { fr: "Se connecter", en: "Sign in" },
  "auth.signUpBtn": { fr: "S'inscrire", en: "Sign up" },
  "auth.noAccount": { fr: "Pas de compte ?", en: "No account?" },
  "auth.haveAccount": { fr: "Deja un compte ?", en: "Already have an account?" },
  "auth.signUpSuccess": { fr: "Compte cree avec succes !", en: "Account created successfully!" },
  "auth.signUpSuccessDesc": { fr: "Un email de bienvenue a ete envoye a votre adresse. Vous pouvez maintenant vous connecter.", en: "A welcome email has been sent to your address. You can now sign in." },
  "auth.goToLogin": { fr: "Aller a la connexion", en: "Go to sign in" },
  "auth.welcome": { fr: "Bienvenue sur Teamwil", en: "Welcome to Teamwil" },
  "auth.welcomeDesc": { fr: "Connectez-vous pour acceder a votre espace de gestion des tickets", en: "Sign in to access your ticket management space" },
  "auth.createDesc": { fr: "Rejoignez Teamwil Consulting pour gerer vos tickets", en: "Join Teamwil Consulting to manage your tickets" },
  "auth.admin": { fr: "Administrateur", en: "Administrator" },
  "auth.agent": { fr: "Agent", en: "Agent" },
  "auth.user": { fr: "Demandeur", en: "Requester" },
  "auth.viewer": { fr: "Lecteur", en: "Viewer" },

  // Problems
  "problems.title": { fr: "Problem Management", en: "Problem Management" },
  "problems.subtitle": { fr: "Suivez les incidents recurrents, leurs causes racines et correctifs permanents.", en: "Track recurring incidents, root causes, and permanent fixes." },
  "problems.noData": { fr: "Aucun probleme detecte pour le moment.", en: "No problem records detected yet." },
  "problems.view": { fr: "Voir le detail", en: "View details" },
  "auth.intern": { fr: "Stagiaire", en: "Intern" },
  "seniority.intern": { fr: "Stagiaire", en: "Intern" },
  "seniority.junior": { fr: "Junior", en: "Junior" },
  "seniority.middle": { fr: "Intermediaire", en: "Middle" },
  "seniority.senior": { fr: "Senior", en: "Senior" },
  "auth.invalidCredentials": { fr: "Email ou mot de passe incorrect", en: "Invalid email or password" },
  "auth.emailExists": { fr: "Cet email est deja utilise", en: "This email is already in use" },
  "auth.emailNotVerified": { fr: "Veuillez verifier votre email avant de vous connecter", en: "Please verify your email before signing in" },
  "auth.passwordMismatch": { fr: "Les mots de passe ne correspondent pas", en: "Passwords do not match" },
  "auth.passwordTooShort": { fr: "Le mot de passe doit contenir au moins 8 caracteres", en: "Password must be at least 8 characters" },
  "auth.signingIn": { fr: "Connexion en cours...", en: "Signing in..." },
  "auth.signingUp": { fr: "Inscription en cours...", en: "Signing up..." },
  "auth.continueWithGoogle": { fr: "Continuer avec Google", en: "Continue with Google" },
  "auth.orContinueWithEmail": { fr: "ou continuer avec email", en: "or continue with email" },
  "auth.orCreateWithEmail": { fr: "ou creer avec email", en: "or create with email" },
  "auth.oauthFailed": { fr: "Connexion Google impossible.", en: "Google sign-in failed." },
  "auth.google_authorization_denied": { fr: "Autorisation Google refusee.", en: "Google authorization was denied." },
  "auth.google_oauth_not_configured": {
    fr: "Google OAuth n'est pas configure sur le serveur.",
    en: "Google OAuth is not configured on the server.",
  },
  "auth.google_invalid_state": { fr: "Session OAuth invalide. Reessayez.", en: "Invalid OAuth state. Please retry." },
  "auth.google_exchange_failed": { fr: "Echange OAuth Google echoue.", en: "Google OAuth exchange failed." },
  "auth.google_profile_incomplete": {
    fr: "Profil Google incomplet (email manquant).",
    en: "Incomplete Google profile (missing email).",
  },
  "auth.google_email_not_verified": {
    fr: "L'email Google doit etre verifie avant connexion.",
    en: "Google email must be verified before sign-in.",
  },
  "auth.google_email_conflict": {
    fr: "Cet email est deja lie a un autre compte.",
    en: "This email is already linked to another account.",
  },
  "auth.google_account_conflict": {
    fr: "Ce compte Google est deja associe ailleurs.",
    en: "This Google account is already associated elsewhere.",
  },
  "auth.google_oauth_failed": { fr: "Connexion Google impossible.", en: "Google sign-in failed." },
  "auth.autoEmailSignupHint": {
    fr: "Si votre email n'existe pas encore, un compte sera cree automatiquement et un email de verification sera envoye.",
    en: "If your email does not exist yet, an account will be created automatically and a verification email will be sent.",
  },
  "auth.forgotPassword": { fr: "Mot de passe oublie ?", en: "Forgot password?" },
  "auth.forgotPasswordTitle": { fr: "Recuperer votre compte", en: "Recover your account" },
  "auth.forgotPasswordDesc": {
    fr: "Entrez votre email pour recevoir un lien de reinitialisation de mot de passe.",
    en: "Enter your email to receive a password reset link.",
  },
  "auth.sendResetLink": { fr: "Envoyer le lien", en: "Send reset link" },
  "auth.sendingResetEmail": { fr: "Envoi en cours...", en: "Sending..." },
  "auth.resetEmailSent": {
    fr: "Si ce compte existe, un email de reinitialisation vient d'etre envoye.",
    en: "If this account exists, a reset email has been sent.",
  },
  "auth.resetNow": { fr: "Reinitialiser maintenant", en: "Reset now" },
  "auth.resetPassword": { fr: "Reinitialiser le mot de passe", en: "Reset password" },
  "auth.resetPasswordTitle": { fr: "Choisir un nouveau mot de passe", en: "Choose a new password" },
  "auth.resetPasswordDesc": {
    fr: "Definissez un nouveau mot de passe securise pour votre compte.",
    en: "Set a new secure password for your account.",
  },
  "auth.resetPasswordBtn": { fr: "Mettre a jour le mot de passe", en: "Update password" },
  "auth.resettingPassword": { fr: "Mise a jour...", en: "Updating..." },
  "auth.resetSuccess": {
    fr: "Votre mot de passe a ete reinitialise. Vous pouvez vous connecter.",
    en: "Your password has been reset. You can now sign in.",
  },
  "auth.resetError": { fr: "Impossible de reinitialiser le mot de passe.", en: "Could not reset password." },
  "auth.invalidResetToken": {
    fr: "Le lien de reinitialisation est invalide ou expire.",
    en: "The reset link is invalid or expired.",
  },
  "auth.newPassword": { fr: "Nouveau mot de passe", en: "New password" },
  "auth.backToLogin": { fr: "Retour a la connexion", en: "Back to sign in" },
  "auth.verifyTitle": { fr: "Verification de votre email", en: "Verify your email" },
  "auth.verifyInProgress": { fr: "Verification en cours...", en: "Verifying..." },
  "auth.verifySuccess": { fr: "Votre email a ete verifie.", en: "Your email has been verified." },
  "auth.verifyError": { fr: "Lien de verification invalide ou expire.", en: "Verification link is invalid or expired." },
  "auth.verifyRedirecting": { fr: "Connexion en cours, redirection...", en: "Signing you in, redirecting..." },
  "auth.checkEmail": { fr: "Consultez votre boite mail pour activer votre compte.", en: "Check your inbox to activate your account." },
  "auth.verifyCodeHint": {
    fr: "Entrez le code de verification recu par email ou utilisez le lien de verification.",
    en: "Enter the verification code from email, or use the verification link.",
  },
  "auth.verifyCodeLabel": { fr: "Code de verification", en: "Verification code" },
  "auth.verifyCodePlaceholder": { fr: "123456", en: "123456" },
  "auth.verifyCodeBtn": { fr: "Verifier le code", en: "Verify code" },
  "auth.verifyingCode": { fr: "Verification...", en: "Verifying..." },
  "auth.verifyCodeSuccess": { fr: "Code valide. Compte active.", en: "Code valid. Account activated." },
  "auth.verifyCodeError": { fr: "Impossible de verifier ce code.", en: "Could not verify this code." },
  "auth.invalidVerificationCode": {
    fr: "Code invalide ou expire. Demandez un nouvel email de verification.",
    en: "Invalid or expired code. Request a new verification email.",
  },
  "auth.emailMissingForCode": {
    fr: "Email manquant. Recommencez la creation ou connexion pour recevoir un nouveau code.",
    en: "Missing email. Start sign-up or login again to receive a new code.",
  },
  "auth.verifyNow": { fr: "Verifier maintenant", en: "Verify now" },
  "auth.devToken": { fr: "Token de verification (dev)", en: "Verification token (dev)" },
  "auth.devCode": { fr: "Code de verification (dev)", en: "Verification code (dev)" },

  // Admin
  "admin.title": { fr: "Administration", en: "Administration" },
  "admin.subtitle": { fr: "Gerez les utilisateurs et les controles d'acces", en: "Manage users and access controls" },
  "admin.users": { fr: "Utilisateurs", en: "Users" },
  "admin.totalUsers": { fr: "utilisateurs enregistres", en: "registered users" },
  "admin.name": { fr: "Nom", en: "Name" },
  "admin.email": { fr: "Email", en: "Email" },
  "admin.role": { fr: "Role", en: "Role" },
  "admin.seniority": { fr: "Seniorite", en: "Seniority" },
  "admin.specializations": { fr: "Specialisations", en: "Specializations" },
  "admin.created": { fr: "Date de creation", en: "Created" },
  "admin.actions": { fr: "Actions", en: "Actions" },
  "admin.changeRole": { fr: "Changer le role", en: "Change role" },
  "admin.deleteUser": { fr: "Supprimer", en: "Delete" },
  "admin.accessDenied": { fr: "Acces refuse", en: "Access denied" },
  "admin.accessDeniedDesc": { fr: "Vous n'avez pas les droits d'administration.", en: "You don't have administration rights." },
  "admin.backToDashboard": { fr: "Retour au tableau de bord", en: "Back to dashboard" },
  "admin.you": { fr: "vous", en: "you" },
  "admin.deleteConfirm": {
    fr: "Cette action est irreversible. L'utilisateur sera supprime definitivement.",
    en: "This action is irreversible. The user will be permanently deleted.",
  },
  "admin.emailLogTitle": { fr: "Emails de bienvenue envoyes", en: "Welcome emails sent" },
  "admin.emailLogEmpty": { fr: "Aucun email envoye pour le moment.", en: "No emails sent yet." },

  // General
  "general.loading": { fr: "Chargement...", en: "Loading..." },
  "general.error": { fr: "Erreur", en: "Error" },
  "general.save": { fr: "Enregistrer", en: "Save" },
  "general.delete": { fr: "Supprimer", en: "Delete" },
  "general.confirm": { fr: "Confirmer", en: "Confirm" },
  "general.clear": { fr: "Effacer", en: "Clear" },
} as const

export type TranslationKey = keyof typeof translations

interface I18nContextType {
  locale: Locale
  setLocale: (locale: Locale) => void
  t: (key: TranslationKey, params?: Record<string, string | number>) => string
}

const I18nContext = createContext<I18nContextType | null>(null)

export function I18nProvider({ children }: { children: React.ReactNode }) {
  const [locale, setLocale] = useState<Locale>("fr")

  const t = useCallback(
    (key: TranslationKey, params?: Record<string, string | number>) => {
      let text = (translations[key]?.[locale] ?? key) as string
      if (params) {
        for (const [k, v] of Object.entries(params)) {
          text = text.replace(`{${k}}`, String(v))
        }
      }
      return text
    },
    [locale]
  )

  return (
    <I18nContext.Provider value={{ locale, setLocale, t }}>
      {children}
    </I18nContext.Provider>
  )
}

export function useI18n() {
  const ctx = useContext(I18nContext)
  if (!ctx) throw new Error("useI18n must be used within I18nProvider")
  return ctx
 }
