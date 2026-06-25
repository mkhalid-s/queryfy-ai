<template>
  <component
    :is="cardComponent"
    :tool-name="toolName"
    :args="args"
    :result="result"
    :step-number="stepNumber"
    :is-pending="isPending"
  />
</template>

<script setup>
import { computed } from 'vue'
import SearchTablesCard from './SearchTablesCard.vue'
import GetTableSchemaCard from './GetTableSchemaCard.vue'
import LookupBusinessTermCard from './LookupBusinessTermCard.vue'
import ExecuteSqlCard from './ExecuteSqlCard.vue'
import GetSampleDataCard from './GetSampleDataCard.vue'
import GenericToolCard from './GenericToolCard.vue'

/**
 * ToolCard — dispatcher that picks the right typed card based on
 * the tool name. Falls back to GenericToolCard for unknown tools.
 *
 * Closes Tier A9 of the 2026-05-09 audit rollout. Source: Reviewer D move B.
 *
 * Each child card receives the same props (tool-name, args, result,
 * step-number, is-pending). Cards do their own parsing via
 * `parsers.js` so this dispatcher stays dumb — adding a new tool
 * means adding a new card + a new line in COMPONENT_MAP.
 */

const props = defineProps({
  toolName: { type: String, required: true },
  args: { type: Object, default: () => ({}) },
  result: { type: String, default: '' },
  stepNumber: { type: Number, default: 0 },
  isPending: { type: Boolean, default: false }
})

// Tool name → typed card. Unknown tools fall through to
// GenericToolCard so the timeline never has a hole.
const COMPONENT_MAP = {
  search_tables: SearchTablesCard,
  get_table_schema: GetTableSchemaCard,
  lookup_business_term: LookupBusinessTermCard,
  execute_sql: ExecuteSqlCard,
  execute_and_analyze: ExecuteSqlCard,
  get_sample_data: GetSampleDataCard
}

const cardComponent = computed(
  () => COMPONENT_MAP[props.toolName] || GenericToolCard
)
</script>
