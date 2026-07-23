import { toNodeHandler } from 'better-auth/node'

import { getAuth } from '../_lib/auth.js'

let handler

export default async function authHandler(req, res) {
  res.setHeader('Cache-Control', 'no-store')
  handler ||= toNodeHandler(getAuth())
  return handler(req, res)
}
