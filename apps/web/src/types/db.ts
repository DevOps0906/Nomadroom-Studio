
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
            "api_quota_daily": {
                  Row: {
                    "day": string,"search_units": number,"units": number
                  }
                  ComputedFields: never
                  Insert: {
                    "day": string,"search_units"?: number,"units"?: number
                  }
                  Update: {
                    "day"?: string,"search_units"?: number,"units"?: number
                  }
                  Relationships: [
                    
                  ]
                },"broadcaster_channels": {
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
      referencedRelation: "candidate_list_v"
      referencedColumns: ["id"]
    },{
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
                },"edit_revisions": {
                  Row: {
                    "approved_at": string | null,"approved_by": string | null,"created_at": string,"created_by": string | null,"derived_from": string | null,"id": string,"job_id": string,"lang": string,"origin": string,"rev_no": number,"schema_version": number,"spec": NonNullable<Json>,"updated_at": string,"validation": NonNullable<Json>,"workspace_id": string
                  }
                  ComputedFields: never
                  Insert: {
                    "approved_at"?: string | null,"approved_by"?: string | null,"created_at"?: string,"created_by"?: string | null,"derived_from"?: string | null,"id"?: string,"job_id": string,"lang"?: string,"origin"?: string,"rev_no": number,"schema_version"?: number,"spec"?: NonNullable<Json>,"updated_at"?: string,"validation"?: NonNullable<Json>,"workspace_id": string
                  }
                  Update: {
                    "approved_at"?: string | null,"approved_by"?: string | null,"created_at"?: string,"created_by"?: string | null,"derived_from"?: string | null,"id"?: string,"job_id"?: string,"lang"?: string,"origin"?: string,"rev_no"?: number,"schema_version"?: number,"spec"?: NonNullable<Json>,"updated_at"?: string,"validation"?: NonNullable<Json>,"workspace_id"?: string
                  }
                  Relationships: [
                    {
      foreignKeyName: "edit_revisions_derived_from_fk"
      columns: ["derived_from","job_id"]
isOneToOne: false
      referencedRelation: "edit_revisions"
      referencedColumns: ["id","job_id"]
    },{
      foreignKeyName: "edit_revisions_job_fk"
      columns: ["job_id","workspace_id"]
isOneToOne: false
      referencedRelation: "production_jobs"
      referencedColumns: ["id","workspace_id"]
    },{
      foreignKeyName: "edit_revisions_workspace_id_fkey"
      columns: ["workspace_id"]
isOneToOne: false
      referencedRelation: "workspaces"
      referencedColumns: ["id"]
    }
                  ]
                },"generation_runs": {
                  Row: {
                    "actual_cost_krw": number | null,"billable": boolean,"confirmed_at": string | null,"confirmed_by": string | null,"created_at": string,"cut_ref": string | null,"duration_sec": number,"error_code": string | null,"est_cost_krw": number,"finalize_token": string | null,"finished_at": string | null,"id": string,"idempotency_key": string,"job_id": string | null,"model": string,"platform": string,"prompt": string,"request_id": string | null,"requested_by": string | null,"result_asset_id": string | null,"source_asset_id": string | null,"status": string,"updated_at": string,"workspace_id": string,"_gen_run_json": Json | null
                  }
                  ComputedFields: "_gen_run_json"
                  Insert: {
                    "actual_cost_krw"?: number | null,"billable"?: boolean,"confirmed_at"?: string | null,"confirmed_by"?: string | null,"created_at"?: string,"cut_ref"?: string | null,"duration_sec": number,"error_code"?: string | null,"est_cost_krw": number,"finalize_token"?: string | null,"finished_at"?: string | null,"id"?: string,"idempotency_key": string,"job_id"?: string | null,"model": string,"platform": string,"prompt": string,"request_id"?: string | null,"requested_by"?: string | null,"result_asset_id"?: string | null,"source_asset_id"?: string | null,"status"?: string,"updated_at"?: string,"workspace_id": string
                  }
                  Update: {
                    "actual_cost_krw"?: number | null,"billable"?: boolean,"confirmed_at"?: string | null,"confirmed_by"?: string | null,"created_at"?: string,"cut_ref"?: string | null,"duration_sec"?: number,"error_code"?: string | null,"est_cost_krw"?: number,"finalize_token"?: string | null,"finished_at"?: string | null,"id"?: string,"idempotency_key"?: string,"job_id"?: string | null,"model"?: string,"platform"?: string,"prompt"?: string,"request_id"?: string | null,"requested_by"?: string | null,"result_asset_id"?: string | null,"source_asset_id"?: string | null,"status"?: string,"updated_at"?: string,"workspace_id"?: string
                  }
                  Relationships: [
                    {
      foreignKeyName: "generation_runs_job_fk"
      columns: ["job_id","workspace_id"]
isOneToOne: false
      referencedRelation: "production_jobs"
      referencedColumns: ["id","workspace_id"]
    },{
      foreignKeyName: "generation_runs_result_fk"
      columns: ["result_asset_id","job_id"]
isOneToOne: false
      referencedRelation: "production_assets"
      referencedColumns: ["id","job_id"]
    },{
      foreignKeyName: "generation_runs_source_fk"
      columns: ["source_asset_id","job_id"]
isOneToOne: false
      referencedRelation: "production_assets"
      referencedColumns: ["id","job_id"]
    },{
      foreignKeyName: "generation_runs_workspace_id_fkey"
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
                    "claimed_by": string | null,"created_at": string,"error": string | null,"finished_at": string | null,"id": string,"idempotency_key": string,"kind": string,"lookup_count": number,"params": NonNullable<Json>,"profile_ids": (string)[],"requested_by": string | null,"result": Json | null,"retry_count": number,"started_at": string | null,"status": string,"stop_requested": boolean,"workspace_id": string
                  }
                  ComputedFields: never
                  Insert: {
                    "claimed_by"?: string | null,"created_at"?: string,"error"?: string | null,"finished_at"?: string | null,"id"?: string,"idempotency_key": string,"kind": string,"lookup_count"?: number,"params"?: NonNullable<Json>,"profile_ids"?: (string)[],"requested_by"?: string | null,"result"?: Json | null,"retry_count"?: number,"started_at"?: string | null,"status"?: string,"stop_requested"?: boolean,"workspace_id": string
                  }
                  Update: {
                    "claimed_by"?: string | null,"created_at"?: string,"error"?: string | null,"finished_at"?: string | null,"id"?: string,"idempotency_key"?: string,"kind"?: string,"lookup_count"?: number,"params"?: NonNullable<Json>,"profile_ids"?: (string)[],"requested_by"?: string | null,"result"?: Json | null,"retry_count"?: number,"started_at"?: string | null,"status"?: string,"stop_requested"?: boolean,"workspace_id"?: string
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
      referencedRelation: "candidate_list_v"
      referencedColumns: ["id"]
    },{
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
                },"production_assets": {
                  Row: {
                    "created_at": string,"created_by": string | null,"duration_sec": number | null,"id": string,"job_id": string,"kind": string,"mime": string,"parent_asset_id": string | null,"render_run_id": string | null,"review_checks": Json | null,"reviewed": boolean,"rights": Json | null,"size_bytes": number | null,"status": string,"storage_path": string,"workspace_id": string
                  }
                  ComputedFields: never
                  Insert: {
                    "created_at"?: string,"created_by"?: string | null,"duration_sec"?: number | null,"id"?: string,"job_id": string,"kind": string,"mime": string,"parent_asset_id"?: string | null,"render_run_id"?: string | null,"review_checks"?: Json | null,"reviewed"?: boolean,"rights"?: Json | null,"size_bytes"?: number | null,"status"?: string,"storage_path": string,"workspace_id": string
                  }
                  Update: {
                    "created_at"?: string,"created_by"?: string | null,"duration_sec"?: number | null,"id"?: string,"job_id"?: string,"kind"?: string,"mime"?: string,"parent_asset_id"?: string | null,"render_run_id"?: string | null,"review_checks"?: Json | null,"reviewed"?: boolean,"rights"?: Json | null,"size_bytes"?: number | null,"status"?: string,"storage_path"?: string,"workspace_id"?: string
                  }
                  Relationships: [
                    {
      foreignKeyName: "production_assets_job_fk"
      columns: ["job_id","workspace_id"]
isOneToOne: false
      referencedRelation: "production_jobs"
      referencedColumns: ["id","workspace_id"]
    },{
      foreignKeyName: "production_assets_parent_fk"
      columns: ["parent_asset_id","job_id"]
isOneToOne: false
      referencedRelation: "production_assets"
      referencedColumns: ["id","job_id"]
    },{
      foreignKeyName: "production_assets_render_run_fk"
      columns: ["render_run_id","job_id"]
isOneToOne: false
      referencedRelation: "render_runs"
      referencedColumns: ["id","job_id"]
    },{
      foreignKeyName: "production_assets_workspace_id_fkey"
      columns: ["workspace_id"]
isOneToOne: false
      referencedRelation: "workspaces"
      referencedColumns: ["id"]
    }
                  ]
                },"production_jobs": {
                  Row: {
                    "affiliates": NonNullable<Json>,"ai_draft_count": number,"ai_draft_requests": NonNullable<Json>,"brief": Json | null,"candidate_id": string | null,"claimed_by": string | null,"comment_keyword": string | null,"completed_at": string | null,"created_at": string,"credit": string | null,"current_ja_revision_id": string | null,"current_revision_id": string | null,"error_code": string | null,"failed_stage": string | null,"format": string,"id": string,"idempotency_key": string,"kind": string,"lang": string,"license_cc": boolean | null,"preset_version": string,"requested_by": string | null,"retry_count": number,"rights_confirmed": boolean,"rights_confirmed_at": string | null,"rights_confirmed_by": string | null,"segment_len_sec": number,"source_kind": string,"source_meta": Json | null,"source_start_sec": number,"source_url": string | null,"status": string,"title": string,"transcribe_error": string | null,"transcribe_state": string | null,"transcribe_updated_at": string | null,"updated_at": string,"vertical": string | null,"workspace_id": string
                  }
                  ComputedFields: never
                  Insert: {
                    "affiliates"?: NonNullable<Json>,"ai_draft_count"?: number,"ai_draft_requests"?: NonNullable<Json>,"brief"?: Json | null,"candidate_id"?: string | null,"claimed_by"?: string | null,"comment_keyword"?: string | null,"completed_at"?: string | null,"created_at"?: string,"credit"?: string | null,"current_ja_revision_id"?: string | null,"current_revision_id"?: string | null,"error_code"?: string | null,"failed_stage"?: string | null,"format"?: string,"id"?: string,"idempotency_key": string,"kind"?: string,"lang"?: string,"license_cc"?: boolean | null,"preset_version": string,"requested_by"?: string | null,"retry_count"?: number,"rights_confirmed"?: boolean,"rights_confirmed_at"?: string | null,"rights_confirmed_by"?: string | null,"segment_len_sec": number,"source_kind"?: string,"source_meta"?: Json | null,"source_start_sec"?: number,"source_url"?: string | null,"status"?: string,"title": string,"transcribe_error"?: string | null,"transcribe_state"?: string | null,"transcribe_updated_at"?: string | null,"updated_at"?: string,"vertical"?: string | null,"workspace_id": string
                  }
                  Update: {
                    "affiliates"?: NonNullable<Json>,"ai_draft_count"?: number,"ai_draft_requests"?: NonNullable<Json>,"brief"?: Json | null,"candidate_id"?: string | null,"claimed_by"?: string | null,"comment_keyword"?: string | null,"completed_at"?: string | null,"created_at"?: string,"credit"?: string | null,"current_ja_revision_id"?: string | null,"current_revision_id"?: string | null,"error_code"?: string | null,"failed_stage"?: string | null,"format"?: string,"id"?: string,"idempotency_key"?: string,"kind"?: string,"lang"?: string,"license_cc"?: boolean | null,"preset_version"?: string,"requested_by"?: string | null,"retry_count"?: number,"rights_confirmed"?: boolean,"rights_confirmed_at"?: string | null,"rights_confirmed_by"?: string | null,"segment_len_sec"?: number,"source_kind"?: string,"source_meta"?: Json | null,"source_start_sec"?: number,"source_url"?: string | null,"status"?: string,"title"?: string,"transcribe_error"?: string | null,"transcribe_state"?: string | null,"transcribe_updated_at"?: string | null,"updated_at"?: string,"vertical"?: string | null,"workspace_id"?: string
                  }
                  Relationships: [
                    {
      foreignKeyName: "production_jobs_candidate_fk"
      columns: ["candidate_id","workspace_id"]
isOneToOne: false
      referencedRelation: "candidate_list_v"
      referencedColumns: ["id","workspace_id"]
    },{
      foreignKeyName: "production_jobs_candidate_fk"
      columns: ["candidate_id","workspace_id"]
isOneToOne: false
      referencedRelation: "candidates"
      referencedColumns: ["id","workspace_id"]
    },{
      foreignKeyName: "production_jobs_claimed_by_fkey"
      columns: ["claimed_by"]
isOneToOne: false
      referencedRelation: "workers"
      referencedColumns: ["id"]
    },{
      foreignKeyName: "production_jobs_current_ja_revision_fk"
      columns: ["current_ja_revision_id","id"]
isOneToOne: false
      referencedRelation: "edit_revisions"
      referencedColumns: ["id","job_id"]
    },{
      foreignKeyName: "production_jobs_current_revision_fk"
      columns: ["current_revision_id","id"]
isOneToOne: false
      referencedRelation: "edit_revisions"
      referencedColumns: ["id","job_id"]
    },{
      foreignKeyName: "production_jobs_workspace_id_fkey"
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
                },"render_runs": {
                  Row: {
                    "attempt": number,"claimed_by": string | null,"created_at": string,"error_code": string | null,"error_stage": string | null,"finished_at": string | null,"hook_audio_asset_id": string | null,"id": string,"idempotency_key": string,"job_id": string,"lang": string,"mp4_asset_id": string | null,"preset_version": string,"progress_pct": number,"progress_stage": string | null,"report_asset_id": string | null,"requested_by": string | null,"retry_of": string | null,"revision_id": string,"started_at": string | null,"status": string,"updated_at": string,"workspace_id": string
                  }
                  ComputedFields: never
                  Insert: {
                    "attempt"?: number,"claimed_by"?: string | null,"created_at"?: string,"error_code"?: string | null,"error_stage"?: string | null,"finished_at"?: string | null,"hook_audio_asset_id"?: string | null,"id"?: string,"idempotency_key": string,"job_id": string,"lang"?: string,"mp4_asset_id"?: string | null,"preset_version": string,"progress_pct"?: number,"progress_stage"?: string | null,"report_asset_id"?: string | null,"requested_by"?: string | null,"retry_of"?: string | null,"revision_id": string,"started_at"?: string | null,"status"?: string,"updated_at"?: string,"workspace_id": string
                  }
                  Update: {
                    "attempt"?: number,"claimed_by"?: string | null,"created_at"?: string,"error_code"?: string | null,"error_stage"?: string | null,"finished_at"?: string | null,"hook_audio_asset_id"?: string | null,"id"?: string,"idempotency_key"?: string,"job_id"?: string,"lang"?: string,"mp4_asset_id"?: string | null,"preset_version"?: string,"progress_pct"?: number,"progress_stage"?: string | null,"report_asset_id"?: string | null,"requested_by"?: string | null,"retry_of"?: string | null,"revision_id"?: string,"started_at"?: string | null,"status"?: string,"updated_at"?: string,"workspace_id"?: string
                  }
                  Relationships: [
                    {
      foreignKeyName: "render_runs_claimed_by_fkey"
      columns: ["claimed_by"]
isOneToOne: false
      referencedRelation: "workers"
      referencedColumns: ["id"]
    },{
      foreignKeyName: "render_runs_hook_audio_asset_fk"
      columns: ["hook_audio_asset_id","job_id"]
isOneToOne: false
      referencedRelation: "production_assets"
      referencedColumns: ["id","job_id"]
    },{
      foreignKeyName: "render_runs_job_fk"
      columns: ["job_id","workspace_id"]
isOneToOne: false
      referencedRelation: "production_jobs"
      referencedColumns: ["id","workspace_id"]
    },{
      foreignKeyName: "render_runs_mp4_asset_fk"
      columns: ["mp4_asset_id","job_id"]
isOneToOne: false
      referencedRelation: "production_assets"
      referencedColumns: ["id","job_id"]
    },{
      foreignKeyName: "render_runs_report_asset_fk"
      columns: ["report_asset_id","job_id"]
isOneToOne: false
      referencedRelation: "production_assets"
      referencedColumns: ["id","job_id"]
    },{
      foreignKeyName: "render_runs_retry_of_fk"
      columns: ["retry_of","job_id"]
isOneToOne: false
      referencedRelation: "render_runs"
      referencedColumns: ["id","job_id"]
    },{
      foreignKeyName: "render_runs_revision_fk"
      columns: ["revision_id","job_id","lang"]
isOneToOne: false
      referencedRelation: "edit_revisions"
      referencedColumns: ["id","job_id","lang"]
    },{
      foreignKeyName: "render_runs_workspace_id_fkey"
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
                    "created_at": string,"gen_job_cap_krw": number,"gen_monthly_budget_krw": number,"id": string,"name": string
                  }
                  ComputedFields: never
                  Insert: {
                    "created_at"?: string,"gen_job_cap_krw"?: number,"gen_monthly_budget_krw"?: number,"id"?: string,"name": string
                  }
                  Update: {
                    "created_at"?: string,"gen_job_cap_krw"?: number,"gen_monthly_budget_krw"?: number,"id"?: string,"name"?: string
                  }
                  Relationships: [
                    
                  ]
                }
          }
          Views: {
            "candidate_list_v": {
                  Row: {
                    "category": string | null,"channel_id": string | null,"channel_title": string | null,"created_at": string,"curr_observed_at": string | null,"curr_view_count": number | null,"display_status": string | null,"first_job_id": string | null,"format": string | null,"genre": string | null,"growth_pct": number | null,"id": string,"is_broadcaster": boolean,"latest_observed_at": string | null,"license_cc": boolean | null,"market": string | null,"prev_observed_at": string | null,"prev_view_count": number | null,"reason": string | null,"rep_profile_id": string | null,"rep_status": string | null,"status_changed_at": string | null,"thumbnail_url": string | null,"title": string,"used": boolean,"used_at": string | null,"video_id": string,"workspace_id": string
                  }
                  ComputedFields: never
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
                }
          }
          Functions: {
            "_ai_draft_json":
{ Args: { "p_count": number,"p_replay": boolean,"p_req": Json }; Returns: Json
                           },
"_ai_draft_set":
{ Args: { "p_job": string,"p_key": string,"p_patch": Json }; Returns: Json
                           },
"_gen_budget":
{ Args: { "p_job": string,"p_workspace": string }; Returns: Json
                           },
"_gen_check_source":
{ Args: { "p_asset": string,"p_job": string,"p_workspace": string }; Returns: undefined
                           },
"_gen_expire_stalled":
{ Args: { "p_run": string }; Returns: undefined
                           },
"_gen_require_budget":
{ Args: { "p_est": number,"p_job": string,"p_workspace": string }; Returns: Json
                           },
"_gen_run_json":
{ Args: { "p_run": Omit<Database["public"]['Tables']["generation_runs"]['Row'], Database["public"]['Tables']["generation_runs"]['ComputedFields']> }; Returns: Json
                           },
"_render_run_json":
{ Args: { "p_created": boolean,"p_run": Omit<Database["public"]['Tables']["render_runs"]['Row'], Database["public"]['Tables']["render_runs"]['ComputedFields']> }; Returns: Json
                           },
"apply_collect_batch":
{ Args: { "p_job": string,"p_payload": Json,"p_profile": string,"p_worker": string,"p_workspace": string }; Returns: number
                           },
"apply_search_batch":
{ Args: { "p_job": string,"p_payload": Json,"p_profile": string,"p_workspace": string }; Returns: number
                           },
"apply_verify_batch":
{ Args: { "p_job": string,"p_payload": Json,"p_workspace": string }; Returns: number
                           },
"approve_production_revision":
{ Args: { "p_job": string,"p_rev_no": number,"p_updated_at": string,"p_user": string,"p_validation": Json,"p_workspace": string }; Returns: Json
                           },
"begin_generation_refresh":
{ Args: { "p_job": string,"p_run": string,"p_workspace": string }; Returns: Json
                           },
"claim_generation_finalize":
{ Args: { "p_run": string,"p_workspace": string }; Returns: Json
                           },
"claim_production_task":
{ Args: { "p_worker": string,"p_workspace": string }; Returns: Json
                           } |
{ Args: { "p_formats": (string)[],"p_worker": string,"p_workspace": string }; Returns: Json
                           },
"confirm_generation_run":
{ Args: { "p_job": string,"p_run": string,"p_user": string,"p_workspace": string }; Returns: Json
                           },
"create_ai_draft_revision":
{ Args: { "p_facts"?: Json,"p_job": string,"p_key": string,"p_spec": Json,"p_user": string,"p_validation": Json,"p_variants"?: Json,"p_workspace": string }; Returns: Json
                           },
"expire_production_offline":
{ Args: { "p_workspace": string }; Returns: Json
                           },
"fail_ai_draft":
{ Args: { "p_job": string,"p_key": string,"p_workspace": string }; Returns: undefined
                           },
"finish_generation_run":
{ Args: { "p_actual_cost": number,"p_asset": string,"p_error": string,"p_path": string,"p_run": string,"p_size": number,"p_status": string,"p_token": string,"p_workspace": string }; Returns: Json
                           },
"finish_production_task":
{ Args: { "p_asset_ids": (string)[],"p_error_code": string,"p_error_stage": string,"p_kind": string,"p_meta": Json,"p_spec": Json,"p_status": string,"p_task": string,"p_validation": Json,"p_worker": string,"p_workspace": string }; Returns: Json
                           },
"is_workspace_member":
{ Args: { "ws": string }; Returns: boolean
                           },
"mark_generation_submitted":
{ Args: { "p_error": string,"p_outcome": string,"p_request_id": string,"p_run": string,"p_workspace": string }; Returns: Json
                           },
"production_affiliates_valid":
{ Args: { "p": Json }; Returns: boolean
                           },
"quota_day":
{ Args: { "p_ts": string }; Returns: string
                           },
"quote_generation_run":
{ Args: { "p_cut_ref": string,"p_duration": number,"p_est_cost": number,"p_job": string,"p_key": string,"p_model": string,"p_platform": string,"p_prompt": string,"p_source_asset": string,"p_user": string,"p_workspace": string }; Returns: Json
                           },
"release_search_quota":
{ Args: { "p_units": number }; Returns: undefined
                           },
"request_render_run":
{ Args: { "p_job": string,"p_key": string,"p_lang": string,"p_revision": string,"p_user": string,"p_workspace": string }; Returns: Json
                           },
"reserve_ai_draft":
{ Args: { "p_job": string,"p_key": string,"p_limit": number,"p_user": string,"p_workspace": string }; Returns: Json
                           },
"reserve_collect_lookup":
{ Args: { "p_job": string,"p_n": number,"p_worker": string,"p_workspace": string }; Returns: number
                           },
"reserve_quota":
{ Args: { "p_limit": number,"p_units": number }; Returns: boolean
                           },
"reserve_search_quota":
{ Args: { "p_limit": number,"p_search_limit": number,"p_units": number }; Returns: boolean
                           },
"retry_collect_job":
{ Args: { "p_job": string,"p_workspace": string }; Returns: Json
                           },
"retry_render_run":
{ Args: { "p_job": string,"p_run": string,"p_user": string,"p_workspace": string }; Returns: Json
                           },
"review_generation_run":
{ Args: { "p_checks": Json,"p_job": string,"p_run": string,"p_user": string,"p_workspace": string }; Returns: Json
                           },
"save_production_revision":
{ Args: { "p_base_rev_no": number,"p_job": string,"p_spec": Json,"p_user": string,"p_validation": Json,"p_workspace": string }; Returns: Json
                           },
"set_profile_selection":
{ Args: { "p_ids": (string)[],"p_workspace": string }; Returns: (string)[]
                           },
"stop_collect_job":
{ Args: { "p_job": string,"p_workspace": string }; Returns: Json
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
