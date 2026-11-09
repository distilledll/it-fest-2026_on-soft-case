import { deleteRequest, getJson, patchJson, postJson, putJson } from './http'
import type { ModelProfilePublic, ModelsRegistry, ProfileCreate, ProfilePatch, ProfileTest, RoleMap } from '@/types'

export const listModels = () => getJson<ModelsRegistry>('/models')

export const createProfile = (body: ProfileCreate) => postJson<ModelProfilePublic>('/models', body)

/** Патчим только изменённые поля; api_key: '' — стереть сохранённый ключ. */
export const patchProfile = (id: string, patch: ProfilePatch) =>
  patchJson<ModelProfilePublic>(`/models/${encodeURIComponent(id)}`, patch)

export const deleteProfile = (id: string) => deleteRequest(`/models/${encodeURIComponent(id)}`)

export const setRoles = (roles: RoleMap) => putJson<RoleMap>('/models/roles', roles)

/** Реальный короткий запрос к модели: {ok, reply, latency_s} или {ok: false, error}. */
export const testProfile = (id: string) => postJson<ProfileTest>(`/models/${encodeURIComponent(id)}/test`)

/** Идентификаторы моделей, которые отдаёт сам провайдер. */
export const remoteModels = (id: string) => getJson<string[]>(`/models/${encodeURIComponent(id)}/remote`)
