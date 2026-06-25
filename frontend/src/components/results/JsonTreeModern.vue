<template>
  <div
    class="json-tree-modern"
    :class="{ 'is-root': root }"
  >
    <!-- Object -->
    <template v-if="isObject">
      <div
        v-for="(value, key) in data"
        :key="key"
        class="tree-node"
      >
        <div
          class="node-row"
          @click="toggle(key)"
        >
          <button
            v-if="isExpandable(value)"
            class="toggle-btn"
          >
            <ChevronRight
              :size="14"
              :class="{ rotated: isOpen(key) }"
            />
          </button>
          <span
            v-else
            class="toggle-spacer"
          />

          <span class="node-key">"{{ key }}"</span>
          <span class="node-colon">:</span>

          <template v-if="isExpandable(value)">
            <span class="node-bracket">{{ Array.isArray(value) ? '[' : '{' }}</span>
            <span
              v-if="!isOpen(key)"
              class="node-collapsed"
            >
              <span class="collapsed-count">{{ getCount(value) }}</span>
              <span class="node-bracket">{{ Array.isArray(value) ? ']' : '}' }}</span>
            </span>
          </template>
          <template v-else>
            <span :class="['node-value', getType(value)]">{{ format(value) }}</span>
          </template>
        </div>

        <template v-if="isExpandable(value) && isOpen(key)">
          <div class="node-children">
            <JsonTreeModern
              :data="value"
              :depth="depth + 1"
            />
          </div>
          <div class="node-row closing">
            <span class="toggle-spacer" />
            <span class="node-bracket">{{ Array.isArray(value) ? ']' : '}' }}</span>
          </div>
        </template>
      </div>
    </template>

    <!-- Array -->
    <template v-else-if="isArray">
      <div
        v-for="(value, index) in data"
        :key="index"
        class="tree-node"
      >
        <div
          class="node-row"
          @click="toggle(index)"
        >
          <button
            v-if="isExpandable(value)"
            class="toggle-btn"
          >
            <ChevronRight
              :size="14"
              :class="{ rotated: isOpen(index) }"
            />
          </button>
          <span
            v-else
            class="toggle-spacer"
          />

          <span class="node-index">{{ index }}</span>
          <span class="node-colon">:</span>

          <template v-if="isExpandable(value)">
            <span class="node-bracket">{{ Array.isArray(value) ? '[' : '{' }}</span>
            <span
              v-if="!isOpen(index)"
              class="node-collapsed"
            >
              <span class="collapsed-count">{{ getCount(value) }}</span>
              <span class="node-bracket">{{ Array.isArray(value) ? ']' : '}' }}</span>
            </span>
          </template>
          <template v-else>
            <span :class="['node-value', getType(value)]">{{ format(value) }}</span>
          </template>
        </div>

        <template v-if="isExpandable(value) && isOpen(index)">
          <div class="node-children">
            <JsonTreeModern
              :data="value"
              :depth="depth + 1"
            />
          </div>
          <div class="node-row closing">
            <span class="toggle-spacer" />
            <span class="node-bracket">{{ Array.isArray(value) ? ']' : '}' }}</span>
          </div>
        </template>
      </div>
    </template>

    <!-- Primitive -->
    <template v-else>
      <div class="node-row">
        <span :class="['node-value', getType(data)]">{{ format(data) }}</span>
      </div>
    </template>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { ChevronRight } from 'lucide-vue-next'

const props = defineProps({
  data: { type: [Object, Array, String, Number, Boolean, null], required: true },
  depth: { type: Number, default: 0 },
  root: { type: Boolean, default: false },
  expandedDefault: { type: Boolean, default: false }
})

const openKeys = ref(new Set())

// Auto-expand first few levels (4 levels deep for better NoSQL document visibility)
onMounted(() => {
  if (props.depth < 4 || props.expandedDefault) {
    if (props.data && typeof props.data === 'object') {
      Object.keys(props.data).slice(0, 8).forEach(k => openKeys.value.add(String(k)))
    }
  }
})

const isObject = computed(() => props.data !== null && typeof props.data === 'object' && !Array.isArray(props.data))
const isArray = computed(() => Array.isArray(props.data))

const isExpandable = (val) => val !== null && typeof val === 'object'
const isOpen = (key) => openKeys.value.has(String(key))

const toggle = (key) => {
  const k = String(key)
  if (openKeys.value.has(k)) {
    openKeys.value.delete(k)
  } else {
    openKeys.value.add(k)
  }
  openKeys.value = new Set(openKeys.value)
}

const getType = (val) => {
  if (val === null || val === undefined) return 'type-null'
  if (typeof val === 'string') return 'type-string'
  if (typeof val === 'number') return 'type-number'
  if (typeof val === 'boolean') return 'type-boolean'
  return 'type-default'
}

const format = (val) => {
  if (val === null) return 'null'
  if (val === undefined) return 'undefined'
  if (typeof val === 'string') {
    if (val.length > 120) return `"${val.slice(0, 120)}..."`
    return `"${val}"`
  }
  if (typeof val === 'boolean') return val ? 'true' : 'false'
  if (typeof val === 'number') return val.toLocaleString()
  return String(val)
}

const getCount = (val) => {
  if (Array.isArray(val)) return `${val.length} item${val.length !== 1 ? 's' : ''}`
  return `${Object.keys(val).length} field${Object.keys(val).length !== 1 ? 's' : ''}`
}
</script>

<style scoped>
.json-tree-modern {
  font-family: var(--font-mono);
  font-size: var(--text-sm);
  line-height: 1.8;
}

.json-tree-modern.is-root {
  padding: var(--space-xs) 0;
}

.tree-node {
  position: relative;
}

.node-row {
  display: flex;
  align-items: baseline;
  padding: var(--space-xs) var(--space-sm);
  margin: 0 calc(var(--space-sm) * -1);
  border-radius: var(--radius-xs);
  cursor: default;
  transition: background var(--transition-fast);
}

.node-row:hover {
  background: var(--bg-hover);
}

.node-row.closing {
  padding-top: 0;
  margin-top: -2px;
}

.toggle-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 20px;
  height: 20px;
  margin-right: var(--space-xs);
  padding: 0;
  border: none;
  border-radius: var(--radius-xs);
  background: transparent;
  color: var(--color-primary);
  cursor: pointer;
  flex-shrink: 0;
  transition: all var(--transition-fast);
}

.toggle-btn:hover {
  background: var(--color-primary-light);
}

.toggle-btn svg {
  transition: transform var(--transition-fast);
}

.toggle-btn svg.rotated {
  transform: rotate(90deg);
}

.toggle-spacer {
  width: 24px;
  flex-shrink: 0;
}

.node-key {
  color: var(--color-info);
  font-weight: var(--font-medium);
}

.node-index {
  color: var(--color-secondary);
  font-weight: var(--font-medium);
}

.node-colon {
  color: var(--text-muted);
  margin: 0 var(--space-sm) 0 0;
}

.node-bracket {
  color: var(--text-muted);
  font-weight: var(--font-medium);
}

.node-collapsed {
  display: inline-flex;
  align-items: center;
  gap: var(--space-xs);
  margin-left: var(--space-xs);
}

.collapsed-count {
  font-size: var(--text-xs);
  color: var(--text-muted);
  padding: 2px var(--space-sm);
  background: var(--bg-input);
  border-radius: var(--radius-xs);
}

.node-children {
  margin-left: var(--space-lg);
  padding-left: var(--space-md);
  border-left: 1px solid var(--border-subtle);
}

/* Value Types */
.node-value {
  word-break: break-word;
}

.node-value.type-string {
  color: var(--color-warning);
}

.node-value.type-number {
  color: var(--color-success);
}

.node-value.type-boolean {
  color: var(--color-secondary);
  font-weight: var(--font-semibold);
}

.node-value.type-null {
  color: var(--text-muted);
  font-style: italic;
}

.node-value.type-default {
  color: var(--text-primary);
}
</style>
