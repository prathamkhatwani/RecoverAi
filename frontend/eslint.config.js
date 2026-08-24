import js from '@eslint/js'
import globals from 'globals'
import reactHooks from 'eslint-plugin-react-hooks'
import reactRefresh from 'eslint-plugin-react-refresh'

export default [
  { ignores: ['dist'] },
  {
    files: ['**/*.{js,jsx}'],
    languageOptions: {
      ecmaVersion: 2022,
      globals: globals.browser,
      parserOptions: {
        ecmaVersion: 'latest',
        ecmaFeatures: { jsx: true },
        sourceType: 'module',
      },
    },
    plugins: {
      'react-hooks': reactHooks,
      'react-refresh': reactRefresh,
    },
    rules: {
      ...js.configs.recommended.rules,
      ...reactHooks.configs.recommended.rules,
      'no-unused-vars': ['error', { varsIgnorePattern: '^[A-Z_]', argsIgnorePattern: '^_' }],
      'react-refresh/only-export-components': 'off',
      // Off deliberately. This project fetches in effects and sets a loading flag while the
      // request is in flight, which is what the rule objects to. The alternative it wants is a
      // data-fetching library; adding one to render nine read-only endpoints would be more
      // machinery than the problem deserves. Every such effect here has an abort guard.
      'react-hooks/set-state-in-effect': 'off',
    },
  },
]
