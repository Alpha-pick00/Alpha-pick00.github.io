
  # Cherry.Pick

  ## Running the code

  Run `npm i` to install the dependencies.

  Run `npm run dev` to start the development server.

  ## Price comparison API (Naver Shopping)

  The `/compare` page calls a serverless function at `api/search.js`, which proxies
  the [Naver Shopping Search API](https://developers.naver.com/docs/serviceapi/search/shopping/shopping.md)
  server-side (the API requires a secret key and doesn't allow direct browser calls).

  1. Create a Naver Developers app at https://developers.naver.com/apps/#/register
     and enable the "검색" (Search) API with the 쇼핑 (Shopping) scope.
  2. Copy `.env.example` to `.env` and fill in `NAVER_CLIENT_ID` / `NAVER_CLIENT_SECRET`.
  3. Because `npm run dev` only serves the frontend, use the
     [Vercel CLI](https://vercel.com/docs/cli) (`npx vercel dev`) to run the frontend
     and the `api/search.js` function together locally.

  ## Deployment

  This project is deployed on [Vercel](https://vercel.com) (not GitHub Pages) so the
  `api/` serverless function has somewhere to run. In the Vercel project settings,
  set the root directory to `Cherry-Pick/` and add `NAVER_CLIENT_ID` /
  `NAVER_CLIENT_SECRET` as environment variables (Production + Preview).
  