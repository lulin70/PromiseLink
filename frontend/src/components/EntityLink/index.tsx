import { View, Text } from '@tarojs/components'
import { navigateToEntityDetail } from '../../services/navigation'
import './index.scss'

interface EntityLinkProps {
  entityId: string
  name: string
  company?: string
  entityType?: string
}

const ENTITY_TYPE_ICON: Record<string, string> = {
  person: '👤',
  organization: '🏢',
  location: '📍',
  other: '📌',
}

export default function EntityLink({ entityId, name, company, entityType }: EntityLinkProps) {
  return (
    <View
      className='entity-link-card'
      onClick={(e) => {
        e.stopPropagation()
        navigateToEntityDetail(entityId)
      }}
    >
      <View className='entity-link-avatar'>
        <Text className='entity-link-avatar-text'>
          {entityType ? ENTITY_TYPE_ICON[entityType] || '👤' : name.charAt(0)}
        </Text>
      </View>
      <View className='entity-link-info'>
        <Text className='entity-link-name'>{name}</Text>
        {company && <Text className='entity-link-company'>{company}</Text>}
      </View>
      <Text className='entity-link-arrow'>›</Text>
    </View>
  )
}
