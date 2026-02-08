# Landing Page Deployment Guide

This guide shows how to deploy the landing page to **lisaivalidation.dev** and **lisaivalidation.org** using GitHub Pages.

## Option 1: Deploy via GitHub Pages (Recommended for Quick Launch)

### Step 1: Enable GitHub Pages

1. Go to your GitHub repository settings
2. Navigate to **Pages** (in the left sidebar)
3. Under **Source**, select **Deploy from a branch**
4. Select branch: **main** (or **master**)
5. Select folder: **/landing-page** (or **/docs** if you rename the folder)
6. Click **Save**

GitHub will provide a URL like: `https://alexrabo.github.io/LISAgentValidation/`

### Step 2: Configure Custom Domains

**For lisaivalidation.dev:**

1. In GitHub Pages settings, add custom domain: `lisaivalidation.dev`
2. Check "Enforce HTTPS" (after DNS propagates)
3. In your domain registrar (where you registered the domain), add DNS records:
   ```
   Type: CNAME
   Name: www
   Value: alexrabo.github.io

   Type: A (apex domain)
   Name: @
   Values:
     185.199.108.153
     185.199.109.153
     185.199.110.153
     185.199.111.153
   ```

**For lisaivalidation.org:**

Two options:
- **Option A:** Same setup as .dev (separate custom domain in GitHub Pages - requires a separate repo or branch)
- **Option B:** Redirect .org → .dev at your domain registrar (easiest for Monday)

### Step 3: Verify Deployment

1. Wait for DNS propagation (5-30 minutes)
2. Visit https://lisaivalidation.dev
3. Verify SSL certificate is active

---

## Option 2: Deploy via Netlify (Alternative - Easier DNS)

### Setup

1. Sign up at [netlify.com](https://netlify.com)
2. Click "Add new site" → "Import an existing project"
3. Connect your GitHub repository
4. Set publish directory: `landing-page`
5. Click **Deploy**

### Add Custom Domains

1. Go to **Site settings** → **Domain management**
2. Add custom domain: `lisaivalidation.dev`
3. Follow Netlify's DNS instructions (they provide nameservers)
4. Repeat for `lisaivalidation.org` (or set up redirect)

Netlify automatically provisions SSL certificates.

---

## Option 3: Deploy via Vercel (Alternative)

### Setup

1. Sign up at [vercel.com](https://vercel.com)
2. Click "New Project"
3. Import GitHub repository
4. Set root directory: `landing-page`
5. Click **Deploy**

### Add Custom Domains

1. Go to **Settings** → **Domains**
2. Add domain: `lisaivalidation.dev`
3. Follow DNS instructions
4. Repeat for `lisaivalidation.org`

---

## Recommended for Monday Launch

**Use GitHub Pages + Domain Redirect:**

1. Deploy landing page to GitHub Pages
2. Point `lisaivalidation.dev` to GitHub Pages (primary)
3. Redirect `lisaivalidation.org` → `lisaivalidation.dev` at domain registrar

**Total time:** ~30 minutes (plus DNS propagation wait)

---

## Quick Test Locally

Before deploying, test the landing page locally:

```bash
# Navigate to landing-page directory
cd /Users/alex_o/DevProjects/LISAgentValidation/landing-page

# Start a simple HTTP server
python3 -m http.server 8000

# Open in browser
# http://localhost:8000
```

---

## Files in This Directory

- `index.html` - Main landing page (mobile-responsive, no dependencies)
- `DEPLOY.md` - This deployment guide

The landing page is self-contained (no external dependencies) and works on:
- Desktop browsers
- Mobile devices (responsive design)
- Tablets
- Works with JavaScript disabled

---

## Need Help?

- [GitHub Pages Documentation](https://docs.github.com/en/pages)
- [Netlify Documentation](https://docs.netlify.com)
- [Vercel Documentation](https://vercel.com/docs)
