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
  "nav.settings": { fr: "Parametres", en: "Settings" },
  "nav.collapse": { fr: "Reduire", en: "Collapse" },
  "nav.admin": { fr: "Administration", en: "Administration" },

  // App shell
  "app.title": { fr: "TeamWill Ticket Manager", en: "TeamWill Ticket Manager" },
  "app.user": { fr: "Utilisateur", en: "User" },
  "app.logout": { fr: "Deconnexion", en: "Logout" },
  "app.notifications": { fr: "Notifications", en: "Notifications" },

  // Dashboard
  "dashboard.title": { fr: "Tableau de Bord", en: "Dashboard" },
  "dashboard.subtitle": { fr: "Vue d'ensemble de l'activite des tickets TeamWill Consulting", en: "Overview of TeamWill Consulting ticket activity" },
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
  "form.tags": { fr: "Tags", en: "Tags" },
  "form.addTag": { fr: "Ajouter un tag...", en: "Add a tag..." },
  "form.add": { fr: "Ajouter", en: "Add" },
  "form.cancel": { fr: "Annuler", en: "Cancel" },
  "form.create": { fr: "Creer le Ticket", en: "Create Ticket" },
  "form.aiSuggestions": { fr: "Suggestions IA", en: "AI Suggestions" },
  "form.suggestedPriority": { fr: "Priorite suggeree", en: "Suggested priority" },
  "form.suggestedCategory": { fr: "Categorie suggeree", en: "Suggested category" },
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
  "category.security": { fr: "Securite", en: "Security" },

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
  "detail.notFound": { fr: "Ticket non trouve", en: "Ticket not found" },
  "detail.notFoundDesc": {
    fr: "Le ticket {id} n'existe pas ou a ete supprime.",
    en: "Ticket {id} does not exist or has been deleted.",
  },

  // Chat
  "chat.title": { fr: "Assistant IA - TeamWill", en: "AI Assistant - TeamWill" },
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
  "auth.welcome": { fr: "Bienvenue sur TeamWill", en: "Welcome to TeamWill" },
  "auth.welcomeDesc": { fr: "Connectez-vous pour acceder a votre espace de gestion des tickets", en: "Sign in to access your ticket management space" },
  "auth.createDesc": { fr: "Rejoignez TeamWill Consulting pour gerer vos tickets", en: "Join TeamWill Consulting to manage your tickets" },
  "auth.admin": { fr: "Administrateur", en: "Administrator" },
  "auth.agent": { fr: "Agent", en: "Agent" },
  "auth.viewer": { fr: "Lecteur", en: "Viewer" },
  "auth.invalidCredentials": { fr: "Email ou mot de passe incorrect", en: "Invalid email or password" },
  "auth.emailExists": { fr: "Cet email est deja utilise", en: "This email is already in use" },
  "auth.emailNotVerified": { fr: "Veuillez verifier votre email avant de vous connecter", en: "Please verify your email before signing in" },
  "auth.passwordMismatch": { fr: "Les mots de passe ne correspondent pas", en: "Passwords do not match" },
  "auth.passwordTooShort": { fr: "Le mot de passe doit contenir au moins 6 caracteres", en: "Password must be at least 6 characters" },
  "auth.signingIn": { fr: "Connexion en cours...", en: "Signing in..." },
  "auth.signingUp": { fr: "Inscription en cours...", en: "Signing up..." },
  "auth.verifyTitle": { fr: "Verification de votre email", en: "Verify your email" },
  "auth.verifyInProgress": { fr: "Verification en cours...", en: "Verifying..." },
  "auth.verifySuccess": { fr: "Votre email a ete verifie.", en: "Your email has been verified." },
  "auth.verifyError": { fr: "Lien de verification invalide ou expire.", en: "Verification link is invalid or expired." },
  "auth.checkEmail": { fr: "Consultez votre boite mail pour activer votre compte.", en: "Check your inbox to activate your account." },
  "auth.verifyNow": { fr: "Verifier maintenant", en: "Verify now" },
  "auth.devToken": { fr: "Token de verification (dev)", en: "Verification token (dev)" },

  // Admin
  "admin.title": { fr: "Administration", en: "Administration" },
  "admin.subtitle": { fr: "Gerez les utilisateurs et les controles d'acces", en: "Manage users and access controls" },
  "admin.users": { fr: "Utilisateurs", en: "Users" },
  "admin.totalUsers": { fr: "utilisateurs enregistres", en: "registered users" },
  "admin.name": { fr: "Nom", en: "Name" },
  "admin.email": { fr: "Email", en: "Email" },
  "admin.role": { fr: "Role", en: "Role" },
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
      let text = translations[key]?.[locale] || key
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
