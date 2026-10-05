# Assign DOIM fellows/residents (from the program roster spreadsheet) to the
# publications published on the site, by author name.
#
#   source("tools/trainee-matching/assign_trainees.R")
#   m <- assign_trainees("Copy of 2026-2027 Fellows and Residents List with email only.xlsx")
#
# The publication documents only carry author *names* ("First Middle Last"), no
# affiliations, so every match is probabilistic. Each candidate gets a `score`
# in [0, 1] and a `match_type` explaining it. Requires: data.table, jsonlite,
# readxl, stringi.

suppressPackageStartupMessages({
  library(data.table)
  library(jsonlite)
  library(readxl)
})

# Base scores per match type. Last name always has to match (exactly, or within
# `fuzzy_max_dist` edits when fuzzy matching is enabled).
.TRAINEE_SCORES <- c(
  given_full    = 0.95, # last name + first name (roster or e-mail spelling)
  given_initial = 0.60, # last name + initial only ("J Raper")
  given_differs = 0.05, # last name matches, a different first name is spelled out
  last_only     = 0.10  # author has a single token that equals the last name
)

# ---- helpers ----------------------------------------------------------------

#' Pull the latest site data from the remote (the weekly refresh PR lands on main).
pull_latest <- function(repo = ".", remote = "origin", branch = "main") {
  system2("git", c("-C", shQuote(repo), "fetch", remote), stdout = FALSE, stderr = FALSE)
  out <- system2("git", c("-C", shQuote(repo), "pull", "--ff-only", remote, branch),
                 stdout = TRUE, stderr = TRUE)
  status <- attr(out, "status")
  if (!is.null(status) && status != 0) {
    stop("git pull failed:\n", paste(out, collapse = "\n"), call. = FALSE)
  }
  message("git pull: ", tail(out, 1))
  invisible(out)
}

.REFRESH_BRANCH <- "origin/automation/doim-directory-refresh"

#' Path to a data/ JSON document: the working tree copy, or (when `data_ref` is
#' given, e.g. "origin/automation/doim-directory-refresh") that git ref's copy,
#' read with `git show` so nothing is merged or checked out.
data_file <- function(repo, name, data_ref = NULL) {
  if (is.null(data_ref)) return(file.path(repo, "data", name))
  out <- tempfile(fileext = ".json")
  status <- system2("git", c("-C", shQuote(repo), "show", shQuote(paste0(data_ref, ":data/", name))),
                    stdout = out)
  if (status != 0) stop("could not read data/", name, " from ", data_ref, call. = FALSE)
  out
}

# Tell the user when the weekly refresh branch holds publications the site has not merged yet.
.warn_if_refresh_pending <- function(repo) {
  blob <- function(ref) suppressWarnings(system2(
    "git", c("-C", shQuote(repo), "rev-parse", shQuote(paste0(ref, ":data/publications.json"))),
    stdout = TRUE, stderr = FALSE))
  a <- blob("HEAD"); b <- blob(.REFRESH_BRANCH)
  if (length(a) && length(b) && !identical(a, b)) {
    message("NOTE: ", .REFRESH_BRANCH, " has newer publication data than the checked-out tree ",
            "(likely an unmerged weekly-refresh PR). Re-run with data_ref = \"", .REFRESH_BRANCH,
            "\" to include it.")
  }
}

#' Lower-case ASCII, punctuation (hyphen, apostrophe, period, comma) -> space.
norm_name <- function(x) {
  x <- stringi::stri_trans_general(x, "Latin-ASCII")
  x <- tolower(x)
  x <- gsub("[^a-z ]+", " ", x)
  trimws(gsub("\\s+", " ", x))
}

# Generational/degree suffixes that follow the surname in author strings.
.SUFFIX <- "( (jr|sr|ii|iii|iv|md|do|phd|mph|ms|mbbs))+$"

read_roster <- function(path) {
  r <- as.data.table(read_excel(path))
  setnames(r, c("last", "first", "degree", "program", "email"))
  r[, trainee_id := .I]
  r[, last_n := norm_name(last)]
  r[, first_n := norm_name(first)]
  # The e-mail local part often carries the name the person goes by
  # (Sam.Van.Hook@... for roster first name "Reed").
  r[, email_first := {
    local <- norm_name(sub("@.*$", "", gsub("\\.", " ", email, fixed = FALSE)))
    ifelse(lengths(strsplit(local, " ")) >= 2, sub(" .*$", "", local), NA_character_)
  }]
  r
}

#' Long table of (work, author position, author name) + work metadata.
read_authorships <- function(repo, data_ref = NULL) {
  pubs <- fromJSON(data_file(repo, "publications.json", data_ref), simplifyVector = FALSE)
  det  <- fromJSON(data_file(repo, "publication-details.json", data_ref), simplifyVector = FALSE)
  message("publications.json generated_at: ", pubs$generated_at,
          " (", length(pubs$works), " works)")
  age <- difftime(Sys.time(), as.POSIXct(pubs$generated_at, format = "%Y-%m-%dT%H:%M:%S", tz = "UTC"),
                  units = "days")
  if (age > 8) {
    warning(sprintf("publication data is %.0f days old; the site refreshes weekly", age),
            call. = FALSE)
  }
  works <- rbindlist(lapply(pubs$works, function(w) {
    list(work_id = w$id, title = w$title, year = w$year, doi = w$doi, pmid = w$pmid,
         venue = w$venue, faculty_ids = list(unlist(w$faculty_ids)))
  }))
  auth <- rbindlist(lapply(names(det$details), function(id) {
    a <- det$details[[id]]$authors
    if (!length(a)) return(NULL)
    data.table(work_id = id, author_pos = seq_along(a),
               n_authors = length(a),
               author = vapply(a, function(z) z$name, ""))
  }))
  list(works = works, authors = auth, generated_at = pubs$generated_at)
}

# Is a (raw, un-normalised) given-name token just initials, e.g. "J" or "JR"?
.is_initials <- function(raw_tok, norm_tok) {
  nchar(norm_tok) == 1 | (nchar(norm_tok) <= 3 & raw_tok == toupper(raw_tok) & !grepl("[a-z]", raw_tok))
}

# ---- main -------------------------------------------------------------------

#' Match roster members to publication authors.
#'
#' @param roster_path   xlsx with Last Name / First Name / Degree / Program / E-Mail Address.
#' @param repo          repository root (contains data/).
#' @param pull          run `git pull --ff-only` (and fetch) first so merged weekly refreshes are included.
#' @param data_ref      read data/ from this git ref instead of the working tree, e.g.
#'                      "origin/automation/doim-directory-refresh" for the pending refresh PR.
#' @param min_score     drop candidates scoring below this (default 0.1 drops "different first name" noise).
#' @param fuzzy         also accept near-miss last names (edit distance), see `fuzzy_max_dist`.
#' @param fuzzy_max_dist max edit distance on the normalised last name (only if `fuzzy`).
#'                      Fuzzy hits additionally require a full first-name match.
#' @return data.table, one row per (trainee, authorship) candidate, highest score first.
assign_trainees <- function(roster_path, repo = ".", pull = TRUE, min_score = 0.1,
                            data_ref = NULL, fuzzy = FALSE, fuzzy_max_dist = 1L) {
  if (pull) {
    pull_latest(repo)
    if (is.null(data_ref)) .warn_if_refresh_pending(repo)
  }
  roster <- read_roster(roster_path)
  src    <- read_authorships(repo, data_ref)
  auth   <- src$authors

  # Parse each distinct author string once.
  u <- data.table(author = unique(auth$author))
  u[, raw_toks := strsplit(stringi::stri_trans_general(author, "Latin-ASCII"), "[ .'-]+")]
  u[, norm := norm_name(author)]
  u[, norm_ns := sub(.SUFFIX, "", norm)]      # strip Jr/III/etc.
  u[, padded := paste0(" ", norm_ns)]

  hits <- list()
  for (i in seq_len(nrow(roster))) {
    r <- roster[i]
    key <- paste0(" ", r$last_n)
    ends <- endsWith(u$padded, key)
    kind <- rep("exact", sum(ends))
    cand <- u[ends]
    cand[, last_tail := r$last_n]
    if (fuzzy) {
      # Compare the same number of trailing tokens as the roster surname.
      k <- lengths(strsplit(r$last_n, " "))
      toks <- strsplit(u$norm_ns, " ")
      tails <- vapply(toks, function(t) paste(tail(t, k), collapse = " "), "")
      near <- !ends & lengths(toks) > k &
        abs(nchar(tails) - nchar(r$last_n)) <= fuzzy_max_dist &
        substr(tails, 1, 1) == substr(r$last_n, 1, 1)
      idx <- which(near)
      d <- drop(adist(r$last_n, tails[idx]))
      idx <- idx[d >= 1 & d <= fuzzy_max_dist]
      if (length(idx)) {
        f <- u[idx]; f[, last_tail := tails[idx]]
        cand <- rbind(cand, f)
        kind <- c(kind, rep("fuzzy", length(idx)))
      }
    }
    if (!nrow(cand)) next
    cand[, kind := kind]
    cand[, given := trimws(substr(norm_ns, 1, nchar(norm_ns) - nchar(last_tail)))]
    # Raw given tokens, for telling initials from short names.
    cand[, n_last_tok := lengths(strsplit(last_tail, " "))]
    cand[, g1_raw := mapply(function(t, k) if (length(t) > k) t[1] else "", raw_toks, n_last_tok)]
    cand[, g1 := sub(" .*$", "", given)]

    firsts <- unique(na.omit(c(r$first_n, r$email_first)))
    first_tok <- sub(" .*$", "", firsts)
    full_hit <- function(g, gfull) {
      # Full given name equals a known first name (or its leading token) in any order of detail.
      g %in% first_tok | gfull %in% firsts | vapply(gfull, function(x) any(startsWith(x, paste0(firsts, " "))), NA)
    }
    cand[, match_type := fcase(
      given == "", "last_only",
      full_hit(g1, given), "given_full",
      .is_initials(g1_raw, g1) & substr(g1, 1, 1) %in% substr(first_tok, 1, 1), "given_initial",
      default = "given_differs"
    )]
    cand[, score := unname(.TRAINEE_SCORES[match_type])]
    # Fuzzy last names are only trusted with a full first-name match.
    cand[kind == "fuzzy", score := fifelse(match_type == "given_full", 0.5, 0)]
    cand[kind == "fuzzy", match_type := paste0("fuzzy_last+", match_type)]
    cand[, trainee_id := r$trainee_id]
    hits[[length(hits) + 1L]] <- cand[score >= min_score,
      .(trainee_id, author, match_type, score)]
  }
  hits <- rbindlist(hits)

  # Attach authorships and work metadata.
  m <- merge(hits, auth, by = "author", allow.cartesian = TRUE)
  m <- merge(m, src$works, by = "work_id")
  m <- merge(m, roster[, .(trainee_id, last, first, degree, program, email)], by = "trainee_id")

  # Down-weight when the matched author string is really one of the work's DOIM
  # faculty (a trainee sharing a name with a faculty member is rarer than the faculty
  # member being the author).
  dir <- fromJSON(data_file(repo, "directory.json", data_ref), simplifyVector = FALSE)$faculty
  fac <- data.table(faculty_id = vapply(dir, `[[`, "", "id"),
                    fname = norm_name(sub(",.*$", "", vapply(dir, `[[`, "", "full_name"))))
  m[, norm_author := norm_name(author)]
  # Faculty names carry middle initials/names inconsistently; compare first+last tokens.
  ft <- function(x) { t <- strsplit(x, " ")[[1]]; paste(t[1], t[length(t)]) }
  # A trainee can also be listed as faculty (same person) - that is not a collision.
  trainee_keys <- vapply(paste(roster$first_n, roster$last_n), ft, "")
  trainee_fac <- fac$fname[vapply(fac$fname, ft, "") %in% trainee_keys]
  m[, is_work_faculty := mapply(function(ids, a) {
    fn <- setdiff(fac[faculty_id %in% ids, fname], trainee_fac)
    ft(a) %in% vapply(fn, ft, "")
  }, faculty_ids, norm_author)]
  m[is_work_faculty == TRUE, score := score * 0.3]

  # Corpus-level ambiguity: how many distinct people (distinct author strings)
  # share this trainee's last name + the matched first token. More = less certain.
  m[, n_same_name_strings := uniqueN(author), by = .(trainee_id, match_type)]

  m[, c("faculty_ids", "norm_author") := NULL]
  setorder(m, -score, trainee_id, -year, work_id)
  setcolorder(m, c("trainee_id", "last", "first", "program", "email", "score", "match_type",
                   "author", "author_pos", "n_authors", "work_id", "year", "title", "doi", "pmid",
                   "venue", "is_work_faculty", "n_same_name_strings"))
  attr(m, "publications_generated_at") <- src$generated_at
  attr(m, "roster") <- roster
  attr(m, "faculty") <- fac
  m[]
}

#' Per roster member: best score and how many candidates fall in each band.
#' Roster members with no candidate at all are kept (best = 0), so the counts
#' add up to the whole roster.
summarise_matches <- function(m, roster = attr(m, "roster")) {
  per <- m[, .(best = max(score),
               n_high = sum(score >= 0.8),
               n_medium = sum(score >= 0.4 & score < 0.8),
               n_low = sum(score < 0.4)),
           by = trainee_id]
  if (is.null(roster)) {
    return(merge(per, unique(m[, .(trainee_id, last, first, program)]), by = "trainee_id")[order(-best, last)])
  }
  s <- merge(roster[, .(trainee_id, last, first, program)], per, by = "trainee_id", all.x = TRUE)
  for (col in c("best", "n_high", "n_medium", "n_low")) set(s, which(is.na(s[[col]])), col, 0)
  s[order(-best, last)]
}

#' Write the matches the site needs to data/trainee-matches.json.
#'
#' Published: matched trainees only (name, degree, program), the (trainee, work)
#' links scoring >= `min_publish_score` (default 0.8: full first-name matches only;
#' initial-only matches are not published), the method, and summary counts over the
#' whole roster. Never published: e-mail addresses and unmatched roster members.
export_trainee_matches <- function(m, path = "data/trainee-matches.json", min_publish_score = 0.8) {
  roster <- attr(m, "roster")
  fac    <- attr(m, "faculty")
  gen    <- attr(m, "publications_generated_at")
  links  <- m[score >= min_publish_score]
  s_all  <- summarise_matches(m, roster)
  s      <- s_all[best >= min_publish_score]

  slug <- function(last, first) gsub(" ", "-", paste(norm_name(last), norm_name(first)))
  tid  <- function(id) slug(roster$last[id], roster$first[id])

  # A roster member who is also listed as faculty is one person: link the two.
  ft <- function(x) { t <- strsplit(x, " ")[[1]]; paste(t[1], t[length(t)]) }
  fkeys <- vapply(fac$fname, ft, "")
  rkeys <- vapply(paste(roster$first_n, roster$last_n), ft, "")
  faculty_for <- function(id) {
    hit <- fac$faculty_id[fkeys == rkeys[id]]
    if (length(hit) == 1) hit else NA_character_
  }

  works_per <- links[, .(n_works = uniqueN(work_id)), by = trainee_id]
  trainees <- merge(s[, .(trainee_id, best)], works_per, by = "trainee_id")
  trainees <- trainees[order(trainee_id)]
  by_program <- s_all[, .(roster = .N,
                          matched_high = sum(best >= 0.8),
                          matched_medium_only = sum(best >= 0.4 & best < 0.8),
                          unmatched = sum(best < 0.4)), by = program][order(-roster, program)]

  doc <- list(
    document_type = "doim-trainee-matches",
    schema_version = 1L,
    generated_at = format(Sys.time(), "%Y-%m-%dT%H:%M:%SZ", tz = "UTC"),
    sources = list(publications_generated_at = gen),
    method = list(
      min_published_score = min_publish_score,
      scores = as.list(.TRAINEE_SCORES),
      faculty_penalty = 0.3,
      initial_only_published = FALSE
    ),
    summary = list(
      roster = nrow(roster),
      matched_high = sum(s_all$best >= 0.8),
      matched_medium_only = sum(s_all$best >= 0.4 & s_all$best < 0.8),
      unmatched = sum(s_all$best < 0.4),
      authorships = nrow(links),
      works = uniqueN(links$work_id),
      by_program = by_program
    ),
    trainees = lapply(seq_len(nrow(trainees)), function(i) {
      id <- trainees$trainee_id[i]
      list(id = paste0("t-", tid(id)),
           name = paste(roster$first[id], roster$last[id]),
           degree = roster$degree[id], program = roster$program[id],
           faculty_id = faculty_for(id),
           best_score = trainees$best[i], works = trainees$n_works[i])
    }),
    links = lapply(seq_len(nrow(links)), function(i) {
      list(trainee_id = paste0("t-", tid(links$trainee_id[i])), work_id = links$work_id[i],
           score = round(links$score[i], 3), match_type = links$match_type[i])
    })
  )
  dir.create(dirname(path), showWarnings = FALSE, recursive = TRUE)
  write_json(doc, path, auto_unbox = TRUE, na = "null", pretty = TRUE, digits = NA)
  message("wrote ", path, ": ", nrow(trainees), " trainees, ", nrow(links), " links")
  invisible(doc)
}
