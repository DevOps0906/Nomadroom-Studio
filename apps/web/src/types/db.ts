
export type Json = string | number | boolean | null | { [key: string]: Json | undefined } | Json[]

export type Database = {
  
  "graphql_public": {
          Tables: {
            [_ in never]: never
          }
          Views: {
            [_ in never]: never
          }
          Functions: {
            "graphql":
{ Args: { "extensions"?: Json,"operationName"?: string,"query"?: string,"variables"?: Json }; Returns: Json
                           }
          }
          Enums: {
            [_ in never]: never
          }
          CompositeTypes: {
            [_ in never]: never
          }
        },"public": {
          Tables: {
            "broadcaster_channels": {
                  Row: {
                    "channel_id": string,"channel_title": string,"created_at": string,"id": string,"workspace_id": string
                  }
                  ComputedFields: never
                  Insert: {
                    "channel_id": string,"channel_title": string,"created_at"?: string,"id"?: string,"workspace_id": string
                  }
                  Update: {
                    "channel_id"?: string,"channel_title"?: string,"created_at"?: string,"id"?: string,"workspace_id"?: string
                  }
                  Relationships: [
                    {
      foreignKeyName: "broadcaster_channels_workspace_id_fkey"
      columns: ["workspace_id"]
isOneToOne: false
      referencedRelation: "workspaces"
      referencedColumns: ["id"]
    }
                  ]
                },"candidate_verdicts": {
                  Row: {
                    "candidate_id": string,"curr_observation_id": string | null,"growth_pct": number | null,"id": string,"judged_at": string,"prev_observation_id": string | null,"profile_id": string,"reason": string | null,"status": string,"workspace_id": string
                  }
                  ComputedFields: never
                  Insert: {
                    "candidate_id": string,"curr_observation_id"?: string | null,"growth_pct"?: number | null,"id"?: string,"judged_at"?: string,"prev_observation_id"?: string | null,"profile_id": string,"reason"?: string | null,"status": string,"workspace_id": string
                  }
                  Update: {
                    "candidate_id"?: string,"curr_observation_id"?: string | null,"growth_pct"?: number | null,"id"?: string,"judged_at"?: string,"prev_observation_id"?: string | null,"profile_id"?: string,"reason"?: string | null,"status"?: string,"workspace_id"?: string
                  }
                  Relationships: [
                    {
      foreignKeyName: "candidate_verdicts_candidate_id_fkey"
      columns: ["candidate_id"]
isOneToOne: false
      referencedRelation: "candidates"
      referencedColumns: ["id"]
    },{
      foreignKeyName: "candidate_verdicts_curr_observation_id_fkey"
      columns: ["curr_observation_id"]
isOneToOne: false
      referencedRelation: "observations"
      referencedColumns: ["id"]
    },{
      foreignKeyName: "candidate_verdicts_prev_observation_id_fkey"
      columns: ["prev_observation_id"]
isOneToOne: false
      referencedRelation: "observations"
      referencedColumns: ["id"]
    },{
      foreignKeyName: "candidate_verdicts_profile_id_fkey"
      columns: ["profile_id"]
isOneToOne: false
      referencedRelation: "profiles"
      referencedColumns: ["id"]
    },{
      foreignKeyName: "candidate_verdicts_workspace_id_fkey"
      columns: ["workspace_id"]
isOneToOne: false
      referencedRelation: "workspaces"
      referencedColumns: ["id"]
    }
                  ]
                },"candidates": {
                  Row: {
                    "category": string | null,"channel_id": string | null,"channel_title": string | null,"created_at": string,"first_job_id": string | null,"format": string | null,"genre": string | null,"id": string,"is_broadcaster": boolean,"license_cc": boolean | null,"market": string | null,"rep_profile_id": string | null,"rep_status": string | null,"status_changed_at": string | null,"thumbnail_url": string | null,"title": string,"used": boolean,"used_at": string | null,"video_id": string,"workspace_id": string
                  }
                  ComputedFields: never
                  Insert: {
                    "category"?: string | null,"channel_id"?: string | null,"channel_title"?: string | null,"created_at"?: string,"first_job_id"?: string | null,"format"?: string | null,"genre"?: string | null,"id"?: string,"is_broadcaster"?: boolean,"license_cc"?: boolean | null,"market"?: string | null,"rep_profile_id"?: string | null,"rep_status"?: string | null,"status_changed_at"?: string | null,"thumbnail_url"?: string | null,"title": string,"used"?: boolean,"used_at"?: string | null,"video_id": string,"workspace_id": string
                  }
                  Update: {
                    "category"?: string | null,"channel_id"?: string | null,"channel_title"?: string | null,"created_at"?: string,"first_job_id"?: string | null,"format"?: string | null,"genre"?: string | null,"id"?: string,"is_broadcaster"?: boolean,"license_cc"?: boolean | null,"market"?: string | null,"rep_profile_id"?: string | null,"rep_status"?: string | null,"status_changed_at"?: string | null,"thumbnail_url"?: string | null,"title"?: string,"used"?: boolean,"used_at"?: string | null,"video_id"?: string,"workspace_id"?: string
                  }
                  Relationships: [
                    {
      foreignKeyName: "candidates_first_job_id_fkey"
      columns: ["first_job_id"]
isOneToOne: false
      referencedRelation: "jobs"
      referencedColumns: ["id"]
    },{
      foreignKeyName: "candidates_rep_profile_id_fkey"
      columns: ["rep_profile_id"]
isOneToOne: false
      referencedRelation: "profiles"
      referencedColumns: ["id"]
    },{
      foreignKeyName: "candidates_workspace_id_fkey"
      columns: ["workspace_id"]
isOneToOne: false
      referencedRelation: "workspaces"
      referencedColumns: ["id"]
    }
                  ]
                },"job_profile_runs": {
                  Row: {
                    "chrome_state": string | null,"collected_count": number,"detail": string | null,"id": string,"job_id": string,"position": number,"profile_id": string,"status": string,"updated_at": string,"workspace_id": string
                  }
                  ComputedFields: never
                  Insert: {
                    "chrome_state"?: string | null,"collected_count"?: number,"detail"?: string | null,"id"?: string,"job_id": string,"position": number,"profile_id": string,"status"?: string,"updated_at"?: string,"workspace_id": string
                  }
                  Update: {
                    "chrome_state"?: string | null,"collected_count"?: number,"detail"?: string | null,"id"?: string,"job_id"?: string,"position"?: number,"profile_id"?: string,"status"?: string,"updated_at"?: string,"workspace_id"?: string
                  }
                  Relationships: [
                    {
      foreignKeyName: "job_profile_runs_job_id_fkey"
      columns: ["job_id"]
isOneToOne: false
      referencedRelation: "jobs"
      referencedColumns: ["id"]
    },{
      foreignKeyName: "job_profile_runs_profile_id_fkey"
      columns: ["profile_id"]
isOneToOne: false
      referencedRelation: "profiles"
      referencedColumns: ["id"]
    },{
      foreignKeyName: "job_profile_runs_workspace_id_fkey"
      columns: ["workspace_id"]
isOneToOne: false
      referencedRelation: "workspaces"
      referencedColumns: ["id"]
    }
                  ]
                },"jobs": {
                  Row: {
                    "claimed_by": string | null,"created_at": string,"error": string | null,"finished_at": string | null,"id": string,"idempotency_key": string,"kind": string,"params": NonNullable<Json>,"profile_ids": (string)[],"requested_by": string | null,"result": Json | null,"retry_count": number,"started_at": string | null,"status": string,"stop_requested": boolean,"workspace_id": string
                  }
                  ComputedFields: never
                  Insert: {
                    "claimed_by"?: string | null,"created_at"?: string,"error"?: string | null,"finished_at"?: string | null,"id"?: string,"idempotency_key": string,"kind": string,"params"?: NonNullable<Json>,"profile_ids"?: (string)[],"requested_by"?: string | null,"result"?: Json | null,"retry_count"?: number,"started_at"?: string | null,"status"?: string,"stop_requested"?: boolean,"workspace_id": string
                  }
                  Update: {
                    "claimed_by"?: string | null,"created_at"?: string,"error"?: string | null,"finished_at"?: string | null,"id"?: string,"idempotency_key"?: string,"kind"?: string,"params"?: NonNullable<Json>,"profile_ids"?: (string)[],"requested_by"?: string | null,"result"?: Json | null,"retry_count"?: number,"started_at"?: string | null,"status"?: string,"stop_requested"?: boolean,"workspace_id"?: string
                  }
                  Relationships: [
                    {
      foreignKeyName: "jobs_claimed_by_fkey"
      columns: ["claimed_by"]
isOneToOne: false
      referencedRelation: "workers"
      referencedColumns: ["id"]
    },{
      foreignKeyName: "jobs_workspace_id_fkey"
      columns: ["workspace_id"]
isOneToOne: false
      referencedRelation: "workspaces"
      referencedColumns: ["id"]
    }
                  ]
                },"observations": {
                  Row: {
                    "candidate_id": string,"channel_id": string | null,"id": string,"job_id": string | null,"license_cc": boolean | null,"observed_at": string,"source": string,"view_count": number,"workspace_id": string
                  }
                  ComputedFields: never
                  Insert: {
                    "candidate_id": string,"channel_id"?: string | null,"id"?: string,"job_id"?: string | null,"license_cc"?: boolean | null,"observed_at": string,"source"?: string,"view_count": number,"workspace_id": string
                  }
                  Update: {
                    "candidate_id"?: string,"channel_id"?: string | null,"id"?: string,"job_id"?: string | null,"license_cc"?: boolean | null,"observed_at"?: string,"source"?: string,"view_count"?: number,"workspace_id"?: string
                  }
                  Relationships: [
                    {
      foreignKeyName: "observations_candidate_id_fkey"
      columns: ["candidate_id"]
isOneToOne: false
      referencedRelation: "candidates"
      referencedColumns: ["id"]
    },{
      foreignKeyName: "observations_job_id_fkey"
      columns: ["job_id"]
isOneToOne: false
      referencedRelation: "jobs"
      referencedColumns: ["id"]
    },{
      foreignKeyName: "observations_workspace_id_fkey"
      columns: ["workspace_id"]
isOneToOne: false
      referencedRelation: "workspaces"
      referencedColumns: ["id"]
    }
                  ]
                },"profiles": {
                  Row: {
                    "category": string | null,"cc_only": boolean,"format": string,"id": string,"include_broadcast": boolean,"keywords": (string)[],"market": string,"max_growth_pct": number,"min_views": number,"name": string,"selected": boolean,"updated_at": string,"workspace_id": string
                  }
                  ComputedFields: never
                  Insert: {
                    "category"?: string | null,"cc_only"?: boolean,"format"?: string,"id"?: string,"include_broadcast"?: boolean,"keywords"?: (string)[],"market": string,"max_growth_pct": number,"min_views"?: number,"name": string,"selected"?: boolean,"updated_at"?: string,"workspace_id": string
                  }
                  Update: {
                    "category"?: string | null,"cc_only"?: boolean,"format"?: string,"id"?: string,"include_broadcast"?: boolean,"keywords"?: (string)[],"market"?: string,"max_growth_pct"?: number,"min_views"?: number,"name"?: string,"selected"?: boolean,"updated_at"?: string,"workspace_id"?: string
                  }
                  Relationships: [
                    {
      foreignKeyName: "profiles_workspace_id_fkey"
      columns: ["workspace_id"]
isOneToOne: false
      referencedRelation: "workspaces"
      referencedColumns: ["id"]
    }
                  ]
                },"worker_heartbeats": {
                  Row: {
                    "chrome": NonNullable<Json>,"current_job_id": string | null,"last_seen_at": string,"worker_id": string,"workspace_id": string
                  }
                  ComputedFields: never
                  Insert: {
                    "chrome"?: NonNullable<Json>,"current_job_id"?: string | null,"last_seen_at"?: string,"worker_id": string,"workspace_id": string
                  }
                  Update: {
                    "chrome"?: NonNullable<Json>,"current_job_id"?: string | null,"last_seen_at"?: string,"worker_id"?: string,"workspace_id"?: string
                  }
                  Relationships: [
                    {
      foreignKeyName: "worker_heartbeats_current_job_id_fkey"
      columns: ["current_job_id"]
isOneToOne: false
      referencedRelation: "jobs"
      referencedColumns: ["id"]
    },{
      foreignKeyName: "worker_heartbeats_worker_id_fkey"
      columns: ["worker_id"]
isOneToOne: true
      referencedRelation: "workers"
      referencedColumns: ["id"]
    },{
      foreignKeyName: "worker_heartbeats_workspace_id_fkey"
      columns: ["workspace_id"]
isOneToOne: false
      referencedRelation: "workspaces"
      referencedColumns: ["id"]
    }
                  ]
                },"workers": {
                  Row: {
                    "created_at": string,"id": string,"name": string,"revoked_at": string | null,"token_hash": string,"workspace_id": string
                  }
                  ComputedFields: never
                  Insert: {
                    "created_at"?: string,"id"?: string,"name": string,"revoked_at"?: string | null,"token_hash": string,"workspace_id": string
                  }
                  Update: {
                    "created_at"?: string,"id"?: string,"name"?: string,"revoked_at"?: string | null,"token_hash"?: string,"workspace_id"?: string
                  }
                  Relationships: [
                    {
      foreignKeyName: "workers_workspace_id_fkey"
      columns: ["workspace_id"]
isOneToOne: false
      referencedRelation: "workspaces"
      referencedColumns: ["id"]
    }
                  ]
                },"workspace_members": {
                  Row: {
                    "created_at": string,"role": string,"user_id": string,"workspace_id": string
                  }
                  ComputedFields: never
                  Insert: {
                    "created_at"?: string,"role"?: string,"user_id": string,"workspace_id": string
                  }
                  Update: {
                    "created_at"?: string,"role"?: string,"user_id"?: string,"workspace_id"?: string
                  }
                  Relationships: [
                    {
      foreignKeyName: "workspace_members_workspace_id_fkey"
      columns: ["workspace_id"]
isOneToOne: false
      referencedRelation: "workspaces"
      referencedColumns: ["id"]
    }
                  ]
                },"workspaces": {
                  Row: {
                    "created_at": string,"id": string,"name": string
                  }
                  ComputedFields: never
                  Insert: {
                    "created_at"?: string,"id"?: string,"name": string
                  }
                  Update: {
                    "created_at"?: string,"id"?: string,"name"?: string
                  }
                  Relationships: [
                    
                  ]
                }
          }
          Views: {
            [_ in never]: never
          }
          Functions: {
            "is_workspace_member":
{ Args: { "ws": string }; Returns: boolean
                           },
"set_profile_selection":
{ Args: { "p_ids": (string)[],"p_workspace": string }; Returns: (string)[]
                           }
          }
          Enums: {
            [_ in never]: never
          }
          CompositeTypes: {
            [_ in never]: never
          }
        }
}

type DatabaseWithoutInternals = Omit<Database, '__InternalSupabase'>

type DefaultSchema = DatabaseWithoutInternals[Extract<keyof Database, "public">]

export type Tables<
  DefaultSchemaTableNameOrOptions extends
    | keyof (DefaultSchema["Tables"] & DefaultSchema["Views"])
    | { schema: keyof DatabaseWithoutInternals },
  TableName extends DefaultSchemaTableNameOrOptions extends {
    schema: keyof DatabaseWithoutInternals
  }
    ? keyof (DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Tables"] &
        DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Views"])
    : never = never
> = DefaultSchemaTableNameOrOptions extends { schema: keyof DatabaseWithoutInternals }
  ? (DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Tables"] &
      DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Views"])[TableName] extends {
      Row: infer R
    }
    ? R
    : never
  : DefaultSchemaTableNameOrOptions extends keyof (DefaultSchema["Tables"] & DefaultSchema["Views"])
  ? (DefaultSchema["Tables"] & DefaultSchema["Views"])[DefaultSchemaTableNameOrOptions] extends {
      Row: infer R
    }
    ? R
    : never
  : never

export type TablesInsert<
  DefaultSchemaTableNameOrOptions extends
    | keyof DefaultSchema["Tables"]
    | { schema: keyof DatabaseWithoutInternals },
  TableName extends DefaultSchemaTableNameOrOptions extends {
    schema: keyof DatabaseWithoutInternals
  }
    ? keyof DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Tables"]
    : never = never
> = DefaultSchemaTableNameOrOptions extends { schema: keyof DatabaseWithoutInternals }
  ? DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Tables"][TableName] extends {
      Insert: infer I
    }
    ? I
    : never
  : DefaultSchemaTableNameOrOptions extends keyof DefaultSchema["Tables"]
  ? DefaultSchema["Tables"][DefaultSchemaTableNameOrOptions] extends {
      Insert: infer I
    }
    ? I
    : never
  : never

export type TablesUpdate<
  DefaultSchemaTableNameOrOptions extends
    | keyof DefaultSchema["Tables"]
    | { schema: keyof DatabaseWithoutInternals },
  TableName extends DefaultSchemaTableNameOrOptions extends {
    schema: keyof DatabaseWithoutInternals
  }
    ? keyof DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Tables"]
    : never = never
> = DefaultSchemaTableNameOrOptions extends { schema: keyof DatabaseWithoutInternals }
  ? DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Tables"][TableName] extends {
      Update: infer U
    }
    ? U
    : never
  : DefaultSchemaTableNameOrOptions extends keyof DefaultSchema["Tables"]
  ? DefaultSchema["Tables"][DefaultSchemaTableNameOrOptions] extends {
      Update: infer U
    }
    ? U
    : never
  : never

export type Enums<
  DefaultSchemaEnumNameOrOptions extends
    | keyof DefaultSchema["Enums"]
    | { schema: keyof DatabaseWithoutInternals },
  EnumName extends DefaultSchemaEnumNameOrOptions extends {
    schema: keyof DatabaseWithoutInternals
  }
    ? keyof DatabaseWithoutInternals[DefaultSchemaEnumNameOrOptions["schema"]]["Enums"]
    : never = never
> = DefaultSchemaEnumNameOrOptions extends { schema: keyof DatabaseWithoutInternals }
  ? DatabaseWithoutInternals[DefaultSchemaEnumNameOrOptions["schema"]]["Enums"][EnumName]
  : DefaultSchemaEnumNameOrOptions extends keyof DefaultSchema["Enums"]
  ? DefaultSchema["Enums"][DefaultSchemaEnumNameOrOptions]
  : never

export type CompositeTypes<
  PublicCompositeTypeNameOrOptions extends
    | keyof DefaultSchema["CompositeTypes"]
    | { schema: keyof DatabaseWithoutInternals },
  CompositeTypeName extends PublicCompositeTypeNameOrOptions extends {
    schema: keyof DatabaseWithoutInternals
  }
    ? keyof DatabaseWithoutInternals[PublicCompositeTypeNameOrOptions["schema"]]["CompositeTypes"]
    : never = never
> = PublicCompositeTypeNameOrOptions extends { schema: keyof DatabaseWithoutInternals }
  ? DatabaseWithoutInternals[PublicCompositeTypeNameOrOptions["schema"]]["CompositeTypes"][CompositeTypeName]
  : PublicCompositeTypeNameOrOptions extends keyof DefaultSchema["CompositeTypes"]
  ? DefaultSchema["CompositeTypes"][PublicCompositeTypeNameOrOptions]
  : never

export const Constants = {
  "graphql_public": {
          Enums: {
            
          }
        },"public": {
          Enums: {
            
          }
        }
} as const
